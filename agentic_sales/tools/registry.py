"""Tool system.

Tools are the only way the agent touches the world. Safety properties enforced here, in code:
  * Tenant/customer identity comes from `ToolContext` (trusted), never from model arguments.
  * Model arguments are validated against a declared schema; unknown args are rejected.
  * Every call (allowed, gated, denied, failed) is written to the audit log.
  * Tools return a status the orchestrator must honour; REQUIRE_APPROVAL is never auto-executed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from ..config.business import BusinessConfig
from ..core.observability import AuditLog
from ..memory.store import TenantMemory
from ..policy.engine import PolicyEngine


class Status(str, Enum):
    OK = "ok"
    NEEDS_APPROVAL = "needs_approval"
    DENIED = "denied"
    ERROR = "error"


@dataclass(frozen=True)
class ToolResult:
    status: Status
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""


@dataclass
class TurnState:
    """Mutable per-turn facts set by trusted tools and read by the orchestrator's guards."""
    payment_verified: bool = False
    payment_mismatch: str | None = None
    payment_claimed_unverified: bool = False
    restricted: bool = False            # fraud posture: no fulfilment-enabling tools this turn
    verified_amounts: set = field(default_factory=set)


@dataclass(frozen=True)
class ToolContext:
    """Trusted, server-built. The model cannot supply or alter any of this."""
    cfg: BusinessConfig
    memory: TenantMemory
    policy: PolicyEngine
    audit: AuditLog
    trace: str
    customer_key: str
    payments: Any = None   # PaymentService | None
    leads: Any = None      # LeadStore | None
    turn: TurnState = field(default_factory=TurnState)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    params: dict[str, type]                  # arg name -> python type
    required: tuple[str, ...]
    handler: Callable[[ToolContext, dict[str, Any]], ToolResult]
    side_effect: str = "read"                # read | write | external

    def validate(self, args: dict[str, Any]) -> str | None:
        unknown = set(args) - set(self.params)
        if unknown:
            return f"unknown args: {sorted(unknown)}"
        for r in self.required:
            if r not in args:
                return f"missing arg: {r}"
        for k, v in args.items():
            want = self.params[k]
            if want is float and isinstance(v, int) and not isinstance(v, bool):
                continue
            if not isinstance(v, want) or (want is int and isinstance(v, bool)):
                return f"arg {k} must be {want.__name__}"
        return None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"duplicate tool {spec.name}")
        self._tools[spec.name] = spec

    def has(self, name: str) -> bool:
        return name in self._tools

    def describe(self) -> str:
        lines = []
        for t in self._tools.values():
            sig = ", ".join(f"{k}: {v.__name__}{'' if k in t.required else '?'}"
                            for k, v in t.params.items())
            lines.append(f"- {t.name}({sig}) — {t.description}")
        return "\n".join(lines)

    def execute(self, name: str, args: Any, ctx: ToolContext) -> ToolResult:
        spec = self._tools.get(name) if isinstance(name, str) else None
        if spec is None:
            res = ToolResult(Status.DENIED, message="unknown tool")
        elif not isinstance(args, dict):
            res = ToolResult(Status.ERROR, message="args must be an object")
        elif (err := spec.validate(args)):
            res = ToolResult(Status.ERROR, message=err)
        else:
            try:
                res = spec.handler(ctx, args)
            except Exception as e:  # tool bugs must not crash a customer turn
                res = ToolResult(Status.ERROR, message=f"{type(e).__name__}")
        ctx.audit.record(ctx.trace, "tool_call", tool=name, args=args if isinstance(args, dict) else None,
                         status=res.status.value, message=res.message)
        return res
