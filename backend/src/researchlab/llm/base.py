"""Model interface. Agents depend on this protocol, not on a vendor SDK."""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLM(Protocol):
    model: str

    async def generate(
        self,
        *,
        step: str,
        system: str,
        prompt: str,
        schema: type[T],
        inputs: BaseModel | None = None,
    ) -> T:
        """Return an instance of ``schema``.

        ``prompt`` is what a real model sees. ``step`` and ``inputs`` exist so the scripted
        demo model can work from the same typed inputs; real models ignore them.
        """
        ...
