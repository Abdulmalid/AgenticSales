"""HTTP API.

    uvicorn agentic_sales.server.app:_default_app --factory      (needs: pip install fastapi uvicorn)

Access model
  /v1/*        Bearer API key -> one tenant (no tenant id accepted from the caller). admin|staff roles.
  /webhooks/*  authenticated by the platform's signature, verified with that tenant's stored secret.
  /public/*    unauthenticated lead capture for landing pages: size-limited, honeypotted, rate-limited.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .. import analytics, approvals
from ..agents.content import ContentError
from ..channels.adapters import ADAPTERS
from ..config.business import BusinessConfig
from ..config.env import load_env
from ..core.types import Channel, InboundMessage
from ..corpus.store import CorpusStore
from ..leads import retention
from ..leads.models import LeadStage
from ..memory.store import customer_key
from ..models.base import TaskKind
from ..payments.paystack import verify_webhook_signature
from ..webpages.landing import LandingError, LandingInput, build_landing_page
from .auth import AuthStore, Principal
from .runtime import Runtimes, TenantRuntime

MAX_BODY = 1_000_000


class RateLimiter:
    def __init__(self, limit: int, window: float = 60.0):
        self.limit, self.window, self.hits = limit, window, defaultdict(deque)

    def check(self, key: str) -> None:
        now, q = time.monotonic(), self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            raise HTTPException(429, "rate limit exceeded")
        q.append(now)


class ChatIn(BaseModel):
    user_id: str = Field(min_length=1, max_length=64, pattern=r"^[\w.@+-]+$")
    text: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=64)


class DecisionIn(BaseModel):
    approve: bool
    reply_text: str | None = Field(default=None, max_length=1000)


class PlanIn(BaseModel):
    brief: str = Field(min_length=3, max_length=2000)
    platform: str
    objective: str
    surface: str | None = Field(default=None, max_length=40)
    n_posts: int = Field(default=1, ge=1, le=5)
    want_video: bool = False


class EditIn(BaseModel):
    caption: str = Field(min_length=1, max_length=2200)


class ScheduleIn(BaseModel):
    when: datetime


class MetricsIn(BaseModel):
    campaign_id: str = Field(max_length=40)
    variant: str = Field(default="A", max_length=10)
    impressions: int = Field(default=0, ge=0)
    clicks: int = Field(default=0, ge=0)
    leads: int = Field(default=0, ge=0)
    conversions: int = Field(default=0, ge=0)
    revenue_kobo: int = Field(default=0, ge=0)


class LandingIn(BaseModel):
    whatsapp: str = Field(max_length=20)
    phone: str | None = Field(default=None, max_length=25)
    location: str | None = Field(default=None, max_length=120)
    tagline: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=300)
    primary_color: str = "#0b6e4f"
    accent_color: str = "#f4a300"
    logo_url: str | None = None
    hero_image_url: str | None = None
    product_images: dict[str, str] = {}


def create_app(root: Path | None = None, runtimes: Runtimes | None = None, auth: AuthStore | None = None) -> FastAPI:
    load_env()
    root = root or Path(os.environ.get("AGENTIC_DATA_DIR", "data"))
    auth = auth or AuthStore(root)
    if runtimes is None:
        idx = root / "index" / "corpus.db"
        corpus = CorpusStore(idx, root / "corpora" / "raw") if idx.exists() else None
        runtimes = Runtimes(root, corpus)
    app = FastAPI(title="AgenticSales", version="0.1", docs_url=None, redoc_url=None)
    api_limit, hook_limit, public_limit = RateLimiter(240), RateLimiter(1200), RateLimiter(20)
    app.state.auth, app.state.runtimes = auth, runtimes

    # ---- dependencies ---------------------------------------------------------------------
    def principal(authorization: str | None = Header(default=None)) -> Principal:
        token = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None
        p = auth.authenticate(token)
        if p is None:
            raise HTTPException(401, "invalid or missing API key")
        api_limit.check(f"{p.tenant_id}")
        return p

    def admin(p: Principal = Depends(principal)) -> Principal:
        if not p.is_admin:
            raise HTTPException(403, "admin role required")
        return p

    def rt_of(p: Principal = Depends(principal)) -> TenantRuntime:
        return runtimes.get(p.tenant_id)

    def tenant_or_404(tenant_id: str) -> TenantRuntime:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,40}", tenant_id) or not auth.tenant_exists(tenant_id):
            raise HTTPException(404, "not found")
        return runtimes.get(tenant_id)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    # ---- webhooks ---------------------------------------------------------------------------
    @app.get("/webhooks/{tenant_id}/{channel}")
    def webhook_handshake(tenant_id: str, channel: str, request: Request) -> Response:
        rt = tenant_or_404(tenant_id)
        adapter = ADAPTERS.get(channel)
        if adapter is None:
            raise HTTPException(404, "unknown channel")
        status, body = adapter.handshake(dict(request.query_params), rt.secrets.get(channel))
        return PlainTextResponse(body, status_code=status)

    @app.post("/webhooks/{tenant_id}/paystack")
    async def paystack_webhook(tenant_id: str, request: Request, bg: BackgroundTasks) -> dict:
        rt = tenant_or_404(tenant_id)
        hook_limit.check(tenant_id)
        raw = await request.body()
        sk = rt.secrets.get("paystack").get("secret_key", "")
        if len(raw) > MAX_BODY or not sk or not verify_webhook_signature(sk, raw, request.headers.get("x-paystack-signature")):
            raise HTTPException(401, "bad signature")
        event = json.loads(raw)
        ref = (event.get("data") or {}).get("reference")
        if event.get("event") == "charge.success" and isinstance(ref, str):
            # never trust the webhook body's amounts: re-verify with the gateway API
            def confirm() -> None:
                with rt.lock:
                    rt.orchestrator.payments.confirm(ref)
            bg.add_task(confirm)
        return {"ok": True}

    @app.post("/webhooks/{tenant_id}/{channel}")
    async def webhook(tenant_id: str, channel: str, request: Request, bg: BackgroundTasks) -> dict:
        rt = tenant_or_404(tenant_id)
        hook_limit.check(tenant_id)
        adapter = ADAPTERS.get(channel)
        if adapter is None:
            raise HTTPException(404, "unknown channel")
        raw = await request.body()
        if len(raw) > MAX_BODY:
            raise HTTPException(413, "payload too large")
        secrets = rt.secrets.get(channel)
        if not adapter.verify_post({k.lower(): v for k, v in request.headers.items()}, raw, secrets):
            with rt.lock:
                rt.orchestrator.audit.record("webhook", "webhook_rejected", channel=channel)
            raise HTTPException(401, "bad signature")
        try:
            payload = json.loads(raw)
        except ValueError:
            raise HTTPException(400, "invalid JSON") from None
        for m in adapter.parse(payload, secrets):
            bg.add_task(rt.handle_and_reply, m)
        return {"ok": True}

    # ---- public lead capture (landing pages) -------------------------------------------------
    @app.post("/public/{tenant_id}/lead")
    async def public_lead(tenant_id: str, request: Request) -> HTMLResponse:
        rt = tenant_or_404(tenant_id)
        public_limit.check(f"{tenant_id}:{request.client.host if request.client else '?'}")
        raw = await request.body()
        if len(raw) > 5000:
            raise HTTPException(413, "too large")
        from urllib.parse import parse_qs
        f = {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "ignore")).items()}
        thanks = HTMLResponse("<!doctype html><meta charset=utf-8><p>Thanks! We'll message you on WhatsApp shortly.</p>")
        if f.get("website"):          # honeypot: bots fill it, humans can't see it
            return thanks
        phone = re.sub(r"\D", "", f.get("phone", ""))
        if phone.startswith("0") and len(phone) == 11:
            phone = "234" + phone[1:]
        if not re.fullmatch(r"\d{10,15}", phone):
            raise HTTPException(422, "valid phone number required")
        with rt.lock:
            lead, _ = rt.orchestrator.leads.get_or_create(customer_key(Channel.WHATSAPP, phone), "landing_page")
            lead.name = (f.get("name") or "")[:80] or lead.name
            if f.get("sku") and rt.cfg.product(f["sku"]):
                lead.interest = f["sku"]
            lead.stage = LeadStage.ENGAGED if lead.stage is LeadStage.NEW else lead.stage
            rt.orchestrator.leads.save(lead)
            rt.orchestrator.leads.event(lead.id, "landing_form", {"message": (f.get("message") or "")[:500]})
        return thanks

    @app.get("/sites/{tenant_id}", response_class=HTMLResponse)
    def site(tenant_id: str) -> HTMLResponse:
        rt = tenant_or_404(tenant_id)
        p = rt.root / "tenants" / tenant_id / "site" / "index.html"
        if not p.exists():
            raise HTTPException(404, "no site published")
        return HTMLResponse(p.read_text(encoding="utf-8"))

    # ---- session / console support ----------------------------------------------------------
    @app.get("/v1/me")
    def me(p: Principal = Depends(principal), rt: TenantRuntime = Depends(rt_of)) -> dict:
        return {"tenant_id": p.tenant_id, "role": p.role, "business_name": rt.cfg.business_name,
                "products": [{"sku": x.sku, "name": x.name, "price_kobo": x.price_kobo} for x in rt.cfg.products],
                "pending_approvals": len(rt.memory.pending_approvals()),
                "channels_configured": sorted(s for s in (*ADAPTERS, "paystack") if rt.secrets.get(s)),
                "models": {"text": rt.orchestrator.router.text.get(TaskKind.CONVERSATION) and
                           rt.orchestrator.router.text[TaskKind.CONVERSATION].name,
                           "image": bool(rt.orchestrator.router.media.get(TaskKind.IMAGE))}}

    @app.get("/v1/outbox")
    def outbox(status: str | None = None, limit: int = Query(50, le=200), rt: TenantRuntime = Depends(rt_of)) -> list[dict]:
        sql, args = "SELECT * FROM outbox", []
        if status:
            sql += " WHERE status=?"
            args.append(status)
        return [dict(r) for r in rt.memory.con.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))]

    # ---- conversations ----------------------------------------------------------------------
    @app.post("/v1/chat")
    def chat(body: ChatIn, rt: TenantRuntime = Depends(rt_of)) -> dict:
        msg = InboundMessage(Channel.WEB, body.user_id, body.conversation_id or f"web-{body.user_id}", body.text)
        res = rt.handle_and_reply(msg)
        return {"reply": res.reply, "escalated": res.escalated, "trace": res.trace, "lead_stage": res.lead_stage,
                "lead_score": res.lead_score, "fraud_risk": res.fraud_risk, "analysis": res.analysis_source}

    @app.get("/v1/audit/{trace}")
    def audit_trace(trace: str, rt: TenantRuntime = Depends(rt_of)) -> list[dict]:
        if not re.fullmatch(r"[0-9a-f]{16}", trace):
            raise HTTPException(422, "bad trace id")
        return rt.orchestrator.audit.trace(trace)

    # ---- leads ------------------------------------------------------------------------------
    @app.get("/v1/leads")
    def leads(stage: str | None = None, band: str | None = None, limit: int = Query(50, le=500),
              rt: TenantRuntime = Depends(rt_of)) -> list[dict]:
        try:
            st = LeadStage(stage) if stage else None
        except ValueError:
            raise HTTPException(422, "unknown stage") from None
        return [l.__dict__ | {"stage": l.stage.value} for l in rt.orchestrator.leads.list(st, band, limit)]

    @app.get("/v1/leads/{lead_id}")
    def lead(lead_id: int, rt: TenantRuntime = Depends(rt_of)) -> dict:
        l = rt.orchestrator.leads.get(lead_id)
        if l is None:
            raise HTTPException(404, "not found")
        from ..leads.engine import score_lead
        sc = score_lead(l, rt.cfg)
        return {"lead": l.__dict__ | {"stage": l.stage.value}, "score_reasons": sc.reasons, "score_calibrated": sc.calibrated,
                "events": rt.orchestrator.leads.events(lead_id), "facts": rt.memory.facts(l.customer_key)}

    @app.delete("/v1/customers/{channel}/{user_id}")
    def erase(channel: str, user_id: str, p: Principal = Depends(admin), rt: TenantRuntime = Depends(rt_of)) -> dict:
        if channel not in ADAPTERS and channel not in ("web", "cli"):
            raise HTTPException(422, "unknown channel")
        rt.erase_customer(f"{channel}:{user_id}")
        return {"erased": True}

    # ---- approvals / outbox / follow-ups ------------------------------------------------------
    @app.get("/v1/approvals")
    def pending(rt: TenantRuntime = Depends(rt_of)) -> list[dict]:
        return rt.memory.pending_approvals()

    @app.post("/v1/approvals/{approval_id}/decision")
    def decide(approval_id: int, body: DecisionIn, p: Principal = Depends(principal),
               rt: TenantRuntime = Depends(rt_of)) -> dict:
        with rt.lock:
            d = approvals.decide(rt.memory, rt.orchestrator.leads, rt.cfg, rt.orchestrator.audit, approval_id,
                                 body.approve, f"{p.role}:{p.tenant_id}", body.reply_text)
        if not d.ok:
            raise HTTPException(409 if "already" in d.detail else 422, d.detail)
        return {"detail": d.detail}

    @app.post("/v1/outbox/flush")
    def flush(rt: TenantRuntime = Depends(rt_of)) -> dict:
        return rt.flush().__dict__

    @app.post("/v1/followups/run")
    def followups(rt: TenantRuntime = Depends(rt_of)) -> dict:
        with rt.lock:
            stale = retention.mark_stale_leads(rt.orchestrator.leads)
            rep = retention.run_due(rt.orchestrator.leads, rt.memory, rt.cfg)
        return {"stale": stale, "followups": rep.__dict__}

    # ---- content / SMM -----------------------------------------------------------------------
    @app.post("/v1/content/plan")
    def plan(body: PlanIn, rt: TenantRuntime = Depends(rt_of)) -> dict:
        try:
            with rt.lock:
                r = rt.content.plan_campaign(body.brief, body.platform, body.objective, surface=body.surface,
                                             n_posts=body.n_posts, want_video=body.want_video)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        except ContentError as e:
            raise HTTPException(502, str(e)) from None
        return r.__dict__

    @app.get("/v1/content")
    def content_list(status: str | None = None, rt: TenantRuntime = Depends(rt_of)) -> list[dict]:
        return rt.content.store.list(status)

    @app.post("/v1/content/{item_id}/approve")
    def content_approve(item_id: int, p: Principal = Depends(principal), rt: TenantRuntime = Depends(rt_of)) -> dict:
        if not rt.content.approve(item_id, f"{p.role}:{p.tenant_id}"):
            raise HTTPException(409, "not approvable (missing, already decided, or has unresolved violations)")
        return {"status": "approved"}

    @app.post("/v1/content/{item_id}/reject")
    def content_reject(item_id: int, p: Principal = Depends(principal), rt: TenantRuntime = Depends(rt_of)) -> dict:
        if not rt.content.reject(item_id, f"{p.role}:{p.tenant_id}"):
            raise HTTPException(409, "cannot reject")
        return {"status": "rejected"}

    @app.put("/v1/content/{item_id}")
    def content_edit(item_id: int, body: EditIn, p: Principal = Depends(principal), rt: TenantRuntime = Depends(rt_of)) -> dict:
        try:
            issues = rt.content.edit(item_id, body.caption, p.role)
        except ContentError as e:
            raise HTTPException(409, str(e)) from None
        return {"violations": issues, "status": "draft" if issues else "pending_approval"}

    @app.post("/v1/content/{item_id}/schedule")
    def content_schedule(item_id: int, body: ScheduleIn, rt: TenantRuntime = Depends(rt_of)) -> dict:
        if not rt.content.schedule(item_id, body.when):
            raise HTTPException(409, "only approved items can be scheduled")
        return {"status": "scheduled"}

    @app.post("/v1/content/{item_id}/image")
    def content_image(item_id: int, rt: TenantRuntime = Depends(rt_of)) -> dict:
        try:
            return {"path": str(rt.content.generate_image(item_id))}
        except ContentError as e:
            raise HTTPException(502, str(e)) from None

    @app.get("/v1/content/{item_id}/media")
    def content_media(item_id: int, rt: TenantRuntime = Depends(rt_of)) -> Response:
        item = rt.content.store.get(item_id)
        path = Path(item["media_path"]) if item and item.get("media_path") else None
        media_root = (rt.root / "tenants" / rt.ctx.tenant_id / "media").resolve()
        if path is None or not path.exists() or media_root not in path.resolve().parents:
            raise HTTPException(404, "no media")      # path must live inside this tenant's media folder
        return Response(path.read_bytes(), media_type="image/png" if path.suffix == ".png" else "image/jpeg",
                        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})

    # ---- landing page --------------------------------------------------------------------------
    @app.post("/v1/landing")
    def landing(body: LandingIn, p: Principal = Depends(admin), rt: TenantRuntime = Depends(rt_of)) -> dict:
        try:
            page = build_landing_page(rt.cfg, LandingInput(**body.model_dump()), f"/public/{p.tenant_id}/lead")
        except LandingError as e:
            raise HTTPException(422, str(e)) from None
        out = rt.root / "tenants" / p.tenant_id / "site" / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page, encoding="utf-8")
        return {"url_path": f"/sites/{p.tenant_id}", "bytes": len(page)}

    # ---- analytics ---------------------------------------------------------------------------
    @app.get("/v1/analytics/funnel")
    def funnel(rt: TenantRuntime = Depends(rt_of)) -> dict:
        return analytics.funnel(rt.orchestrator.leads)

    @app.get("/v1/analytics/campaigns")
    def campaigns(rt: TenantRuntime = Depends(rt_of)) -> list[dict]:
        return analytics.campaign_report(rt.content.store)

    @app.post("/v1/analytics/campaign-metrics")
    def metrics(body: MetricsIn, rt: TenantRuntime = Depends(rt_of)) -> dict:
        rt.content.store.record_metrics(**body.model_dump())
        return {"ok": True}

    # ---- configuration (admin) ---------------------------------------------------------------
    @app.get("/v1/config")
    def get_config(p: Principal = Depends(admin), rt: TenantRuntime = Depends(rt_of)) -> dict:
        import dataclasses
        return dataclasses.asdict(rt.cfg)

    @app.put("/v1/config")
    def put_config(body: dict[str, Any], p: Principal = Depends(admin)) -> dict:
        try:
            BusinessConfig.from_dict(body)
        except (ValueError, TypeError, KeyError) as e:
            raise HTTPException(422, f"invalid config: {e}") from None
        path = Path(root) / "tenants" / p.tenant_id / "business.json"
        path.write_text(json.dumps(body, indent=1), encoding="utf-8")
        runtimes.reload_config(p.tenant_id)
        return {"ok": True}

    @app.put("/v1/secrets/{section}")
    def put_secrets(section: str, body: dict[str, str], p: Principal = Depends(admin)) -> dict:
        if section not in (*ADAPTERS, "paystack"):
            raise HTTPException(422, "unknown section")
        runtimes.get(p.tenant_id).secrets.set(section, body)
        runtimes.reload_config(p.tenant_id)
        return {"stored_keys": sorted(body)}          # values are never echoed back

    @app.get("/v1/secrets")
    def list_secrets(p: Principal = Depends(admin), rt: TenantRuntime = Depends(rt_of)) -> dict:
        return {s: sorted(rt.secrets.get(s)) for s in (*ADAPTERS, "paystack") if rt.secrets.get(s)}

    return app


def _default_app() -> FastAPI:
    """uvicorn factory entry point."""
    return create_app()
