"""CLI: inspect the language/signal analysis offline, or chat as a customer against a tenant.

    python -m agentic_sales.cli analyze "Oga, how much be the last price?"
    python -m agentic_sales.cli chat --tenant demo        # needs ANTHROPIC_API_KEY
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .agents.orchestrator import Orchestrator
from .config.business import load_business_config
from .core.types import Channel, InboundMessage, TenantContext
from .corpus.store import CorpusStore
from .language.analysis import detect_register, extract_signals, plan_style
from .models.anthropic import AnthropicText
from .models.base import ModelRouter, TaskKind
from .tools.builtin import default_registry

ROOT = Path(os.environ.get("AGENTIC_DATA_DIR", "data"))


def _corpus() -> CorpusStore | None:
    try:
        return CorpusStore(ROOT / "index" / "corpus.db", ROOT / "corpora" / "raw")
    except FileNotFoundError as e:
        print(f"[warn] {e}", file=sys.stderr)
        return None


def cmd_analyze(a: argparse.Namespace) -> None:
    r = detect_register(a.text)
    sig = extract_signals(a.text)
    st = plan_style(r, sig)
    print(f"register: {r.primary.value} (conf {r.confidence}, mixed={r.mixed}) scores={r.scores}")
    print(f"signals : {[(s.name, s.evidence) for s in sig]}")
    print(f"style   : slang={st.slang.name} emoji={st.emoji} :: {st.guidance} {st.reasons}")
    store = _corpus()
    if store:
        from .corpus.context import build_reference
        print("--- reference ---\n" + build_reference(store, a.text, r, sig))


def cmd_smm(a: argparse.Namespace) -> None:
    from .corpus.smm import smm_guidance
    store = _corpus()
    if not store:
        return
    for g in smm_guidance(store, a.query, platform=a.platform, objective=a.objective, industry=a.industry,
                          surface=a.surface, region=a.region, limit=a.limit):
        relaxed = f"  (relaxed: dropped {', '.join(g.dropped_filters)})" if g.dropped_filters else ""
        print()
        print(f"## {g.title}")
        print(f"   [{g.platform}/{g.surface}] objective={g.objective} layer={g.layer}{relaxed}")
        print(f"   situation: {g.situation[:200]}")
        for st in g.playbook[:4]:
            print(f"   {st.n}. [{st.automation}] {st.action[:150]}")
        for ap in g.anti_patterns[:2]:
            print(f"   avoid: {ap['pattern'][:120]}")
        print(f"   market: {g.market.get('language_register')} | trust barriers: {g.market.get('trust_barriers')}")
        for c in g.cautions:
            print(f"   CAUTION: {c}")


def cmd_tenant_create(a: argparse.Namespace) -> None:
    import json as _json
    from .server.auth import AuthStore
    cfg = _json.loads(Path(a.config).read_text(encoding="utf-8"))
    key = AuthStore(ROOT).create_tenant(a.id, cfg)
    print(f"tenant '{a.id}' created. Admin API key (shown once, store it safely):")
    print(key)


def cmd_serve(a: argparse.Namespace) -> None:
    import uvicorn
    uvicorn.run("agentic_sales.server.app:_default_app", factory=True, host=a.host, port=a.port)


def cmd_chat(a: argparse.Namespace) -> None:
    ctx = TenantContext(a.tenant)
    cfg = load_business_config(ctx, ROOT)
    router = ModelRouter(text={
        TaskKind.CONVERSATION: AnthropicText(os.environ.get("CONVERSATION_MODEL", "claude-sonnet-5-5")),
        TaskKind.REASONING: AnthropicText(os.environ.get("REASONING_MODEL", "claude-opus-5-5")),
    })
    orch = Orchestrator(ctx, cfg, ROOT, router, default_registry(), _corpus())
    print(f"Chatting with {cfg.business_name}'s agent. Ctrl-D to exit.")
    n = 0
    while True:
        try:
            text = input("customer> ")
        except EOFError:
            break
        n += 1
        res = orch.handle(InboundMessage(Channel.CLI, a.user, f"cli-{a.user}", text, message_id=f"m{n}-{os.getpid()}"))
        print(f"agent> {res.reply}" + ("   [escalated to human]" if res.escalated else ""))
        print(f"       trace={res.trace} flags={res.flags}")


def main() -> None:
    from .config.env import load_env
    load_env()
    ap = argparse.ArgumentParser(prog="agentic_sales")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("analyze")
    p.add_argument("text")
    p.set_defaults(fn=cmd_analyze)
    p = sub.add_parser("smm")
    p.add_argument("query")
    for f in ("platform", "objective", "industry", "surface", "region"):
        p.add_argument(f"--{f}")
    p.add_argument("--limit", type=int, default=2)
    p.set_defaults(fn=cmd_smm)
    p = sub.add_parser("tenant-create")
    p.add_argument("--id", required=True)
    p.add_argument("--config", required=True, help="path to a business.json (see examples/demo_business.json)")
    p.set_defaults(fn=cmd_tenant_create)
    p = sub.add_parser("serve")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(fn=cmd_serve)
    p = sub.add_parser("chat")
    p.add_argument("--tenant", required=True)
    p.add_argument("--user", default="cli-customer")
    p.set_defaults(fn=cmd_chat)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
