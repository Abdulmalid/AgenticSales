"""Channel-agnostic types. Every channel adapter produces `InboundMessage`; the agent core
never sees channel-specific payloads."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

_TENANT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,40}$")


class Channel(str, Enum):
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    TIKTOK = "tiktok"
    X = "x"
    EMAIL = "email"
    WEB = "web"
    CLI = "cli"


@dataclass(frozen=True)
class TenantContext:
    """Identity of the business on whose behalf work is done.

    Created only by trusted code (auth layer / CLI), never from model or customer output.
    Every store and tool takes one and derives all storage paths/keys from it.
    """
    tenant_id: str

    def __post_init__(self) -> None:
        if not _TENANT_ID.match(self.tenant_id):
            raise ValueError(f"invalid tenant_id {self.tenant_id!r}")


@dataclass(frozen=True)
class Attachment:
    kind: str  # image | audio | document | video
    url: str
    mime: str | None = None


@dataclass(frozen=True)
class InboundMessage:
    channel: Channel
    user_id: str            # channel-native id of the customer
    conversation_id: str
    text: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attachments: tuple[Attachment, ...] = ()
    message_id: str | None = None   # for webhook idempotency
