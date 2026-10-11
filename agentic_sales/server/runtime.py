"""Per-tenant runtime: wires stores, agents, models, payment gateway and channels together.

Concurrency note: one lock per tenant serialises its writes (SQLite + a shared connection). That is
correct and simple, but it also serialises that tenant's LLM calls. For high volume per tenant, move to
per-request connections (WAL) and a queue; the module boundaries already allow it.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from ..agents.content import ContentAgent
from ..agents.orchestrator import Orchestrator, TurnResult
from ..channels.adapters import ADAPTERS, ChannelError, ChannelUnavailable
from ..channels.dispatch import SecretStore, flush_outbox
from ..config.business import BusinessConfig, load_business_config
from ..content.store import ContentStore
from ..core.types import InboundMessage, TenantContext
from ..corpus.store import CorpusStore
from ..language.analyzer import Analyzer
from ..language.llm_signals import SignalExtractor
from ..memory.store import TenantMemory
from ..models.anthropic import AnthropicText
from ..models.base import ModelError, ModelRouter, TaskKind
from ..models.gemini import GeminiImage, GeminiText
from ..payments.paystack import NotConfigured, Paystack
from ..tools.builtin import default_registry


def build_router() -> ModelRouter:
    """Provider selection from the environment. Gemini is the default; set MODEL_PROVIDER=anthropic to use
    Claude for conversation + reasoning (needs ANTHROPIC_API_KEY, and ANTHROPIC_WORKSPACE_ID for keys that
    are not workspace-scoped)."""
    r = ModelRouter()
    provider = os.environ.get("MODEL_PROVIDER", "gemini" if os.environ.get("GEMINI_API_KEY") else "anthropic")
    if provider == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
        r.text[TaskKind.CONVERSATION] = AnthropicText(os.environ.get("CONVERSATION_MODEL", "claude-sonnet-5-5"))
        r.text[TaskKind.REASONING] = AnthropicText(os.environ.get("REASONING_MODEL", "claude-opus-5-5"))
    elif os.environ.get("GEMINI_API_KEY"):
        r.text[TaskKind.CONVERSATION] = GeminiText(os.environ.get("CONVERSATION_MODEL", "gemini-flash-lite-latest"))
        r.text[TaskKind.REASONING] = GeminiText(os.environ.get("REASONING_MODEL", "gemini-3-flash-preview"))
    if os.environ.get("GEMINI_API_KEY"):
        r.media[TaskKind.IMAGE] = GeminiImage(os.environ.get("IMAGE_MODEL", "gemini-2.5-flash-image"))
    return r


def build_analyzer() -> Analyzer:
    if os.environ.get("GEMINI_API_KEY"):
        return Analyzer(SignalExtractor(GeminiText(os.environ.get("EXTRACTOR_MODEL", "gemini-flash-lite-latest"))))
    return Analyzer(None)


@dataclass
class TenantRuntime:
    ctx: TenantContext
    root: Path
    orchestrator: Orchestrator
    content: ContentAgent
    secrets: SecretStore
    lock: threading.RLock = field(default_factory=threading.RLock)

    @property
    def cfg(self) -> BusinessConfig:
        return self.orchestrator.cfg

    @property
    def memory(self) -> TenantMemory:
        return self.orchestrator.memory

    def handle_and_reply(self, msg: InboundMessage) -> TurnResult:
        """Process an inbound message and deliver the reply over the same channel (best effort: a failed
        send leaves the reply in the outbox for retry)."""
        with self.lock:
            res = self.orchestrator.handle(msg)
        if res.reply:
            adapter = ADAPTERS.get(msg.channel.value)
            try:
                if adapter is None or msg.channel.value in ("web", "cli"):
                    return res
                adapter.send(msg.user_id, res.reply, self.secrets.get(msg.channel.value))
            except (ChannelUnavailable, ChannelError) as e:
                with self.lock:
                    self.memory.enqueue_message(f"{msg.channel.value}:{msg.user_id}", res.reply, "reply_retry", res.trace)
                    self.orchestrator.audit.record(res.trace, "send_failed", error=str(e)[:200])
        return res

    def flush(self):
        with self.lock:
            return flush_outbox(self.memory, self.secrets)

    def erase_customer(self, customer_key: str) -> None:
        """NDPR right to erasure across every store."""
        with self.lock:
            m = self.memory
            self.orchestrator.leads.erase(customer_key)
            with m.con:
                m.con.execute("DELETE FROM orders WHERE customer_key=?", (customer_key,))
                m.con.execute("DELETE FROM outbox WHERE customer_key=?", (customer_key,))
            m.erase_customer(customer_key)
            self.orchestrator.audit.record("erasure", "customer_erased", customer=customer_key)


class Runtimes:
    def __init__(self, root: Path, corpus: CorpusStore | None, router: ModelRouter | None = None,
                 analyzer: Analyzer | None = None):
        self.root, self.corpus = root, corpus
        self._router = router if router is not None else build_router()
        self._analyzer = analyzer if analyzer is not None else build_analyzer()
        self._cache: dict[str, TenantRuntime] = {}
        self._lock = threading.Lock()

    def get(self, tenant_id: str) -> TenantRuntime:
        with self._lock:
            rt = self._cache.get(tenant_id)
            if rt is None:
                rt = self._cache[tenant_id] = self._build(tenant_id)
            return rt

    def reload_config(self, tenant_id: str) -> None:
        with self._lock:
            self._cache.pop(tenant_id, None)

    def _build(self, tenant_id: str) -> TenantRuntime:
        ctx = TenantContext(tenant_id)
        cfg = load_business_config(ctx, self.root)
        secrets = SecretStore(ctx, self.root)
        gateway = None
        sk = secrets.get("paystack").get("secret_key")
        if sk:
            try:
                gateway = Paystack(sk)
            except NotConfigured:
                gateway = None
        orch = Orchestrator(ctx, cfg, self.root, self._router, default_registry(), self.corpus, self._analyzer, gateway)
        content = ContentAgent(cfg, self.root, tenant_id, self._router, ContentStore(orch.memory), self.corpus)
        return TenantRuntime(ctx, self.root, orch, content, secrets)
