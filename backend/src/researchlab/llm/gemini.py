"""Gemini adapter (google-genai SDK) using JSON-schema constrained output."""

from __future__ import annotations

from google import genai
from google.genai import types
from pydantic import BaseModel

from .base import T


class GeminiLLM:
    def __init__(self, api_key: str, model: str, timeout_seconds: float = 60) -> None:
        self.model = model
        self._timeout = timeout_seconds
        self._client = genai.Client(api_key=api_key)

    async def generate(
        self,
        *,
        step: str,
        system: str,
        prompt: str,
        schema: type[T],
        inputs: BaseModel | None = None,
    ) -> T:
        response = await self._client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_json_schema=schema.model_json_schema(),
                temperature=0.2,
                http_options=types.HttpOptions(timeout=int(self._timeout * 1000)),
            ),
        )
        text = response.text
        if not text:
            raise RuntimeError("Gemini returned no text (possibly blocked or empty)")
        return schema.model_validate_json(text)
