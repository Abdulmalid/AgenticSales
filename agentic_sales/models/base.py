"""Provider-agnostic model layer.

Agents ask the router for a model by *task kind*; they never import a vendor SDK.
Swapping providers (or using different ones per task) is a config change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


class TaskKind(str, Enum):
    REASONING = "reasoning"        # planning, fraud analysis, qualification, orchestration
    CONVERSATION = "conversation"  # customer-facing, latency sensitive
    IMAGE = "image"
    VIDEO = "video"


@dataclass(frozen=True)
class Message:
    role: str  # "user" | "assistant"
    content: str


@dataclass(frozen=True)
class ModelRequest:
    system: str
    messages: tuple[Message, ...]
    max_tokens: int = 1024
    temperature: float = 0.4
    json_mode: bool = False   # ask the provider for strict JSON output where supported


@dataclass(frozen=True)
class ModelResponse:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class ModelError(RuntimeError):
    pass


@runtime_checkable
class TextModel(Protocol):
    name: str

    def complete(self, req: ModelRequest) -> ModelResponse: ...


@runtime_checkable
class MediaModel(Protocol):
    """Image/video generation. Implementations are added in Phase 5; the interface is fixed now
    so content agents can be written against it."""
    name: str

    def generate(self, prompt: str, **options: object) -> bytes: ...


@dataclass
class ModelRouter:
    text: dict[TaskKind, TextModel] = field(default_factory=dict)
    media: dict[TaskKind, MediaModel] = field(default_factory=dict)

    def text_model(self, task: TaskKind) -> TextModel:
        try:
            return self.text[task]
        except KeyError:
            raise ModelError(f"no text model configured for task {task.value!r}") from None

    def media_model(self, task: TaskKind) -> MediaModel:
        try:
            return self.media[task]
        except KeyError:
            raise ModelError(
                f"no media model configured for task {task.value!r} "
                "(image/video providers are not connected yet)") from None
