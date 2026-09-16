"""Extraction of molecular metadata from literature using a remote vLLM server.

vLLM exposes an OpenAI-compatible API, so this module uses the official
``openai`` client pointed at the ``/v1`` endpoint of the server. Structured
output is enforced with the JSON Schema generated from
:class:`lit2mol.schema.MolecularMetadata`.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Literal, Optional, Sequence

from pydantic import BaseModel, Field

from lit2mol.schema import MolecularMetadata, SourceDocument, json_schema

DEFAULT_BASE_URL = "http://localhost:8000/v1"
DEFAULT_API_KEY = "EMPTY"

SYSTEM_PROMPT = """\
You are a meticulous molecular-biology curator. Extract structured metadata \
from the supplied scientific article into JSON that conforms exactly to the \
provided JSON Schema.

Rules:
- Follow the schema strictly. Never invent fields; never omit required fields.
- Represent the chain Gene -> Monomer -> ModifiedMonomer and assemblies as \
Complex objects.
- Put every entity in the correct registry (genes, monomers, modified_monomers, \
complexes) and give each a short, document-unique id.
- Reference other entities by their id using gene_ref, monomer_ref, and \
component_ref. A Complex component may reference a Monomer, a ModifiedMonomer, \
or another Complex, and must carry its stoichiometric count.
- Only assert what the article supports. Attach Evidence (section and a short \
verbatim quote) to each claim. If a value is unknown, omit the optional field.
- Use the controlled vocabularies for modification types and amino-acid codes; \
fall back to "unknown" or "other" plus a description when needed.
- Return a single JSON object and nothing else: no prose, no markdown fences.
"""

USER_TEMPLATE = """\
Focus the extraction on: {focus}

Bibliographic source: {source}

JSON Schema the output must satisfy:
{schema}

Article full text:
---
{text}
---
"""


class VLLMConfig(BaseModel):
    """Connection and decoding settings for a vLLM OpenAI-compatible server."""

    base_url: str = DEFAULT_BASE_URL
    api_key: str = DEFAULT_API_KEY
    model: str
    temperature: float = Field(default=0.0, ge=0.0)
    top_p: float = Field(default=1.0, gt=0.0, le=1.0)
    max_tokens: int = Field(default=8192, gt=0)
    timeout: float = Field(default=600.0, gt=0)
    structured_mode: Literal["guided_json", "response_format"] = "guided_json"
    max_input_chars: int = Field(default=120_000, gt=0)
    seed: Optional[int] = None

    @classmethod
    def from_sources(
        cls,
        cli: Optional[dict[str, Any]] = None,
        toml: Optional[dict[str, Any]] = None,
    ) -> "VLLMConfig":
        """Build a config from CLI args, a TOML table, and environment variables.

        Precedence: non-``None`` CLI values, then TOML values, then environment
        variables (``VLLM_BASE_URL``, ``VLLM_API_KEY``, ``VLLM_MODEL``,
        ``VLLM_STRUCTURED_MODE``), then field defaults.
        """
        cli = {k: v for k, v in (cli or {}).items() if v is not None}
        toml = dict(toml or {})

        unknown = set(toml) - set(cls.model_fields)
        if unknown:
            raise ValueError(f"unknown [vllm] keys: {sorted(unknown)}")

        env = {
            "base_url": os.environ.get("VLLM_BASE_URL"),
            "api_key": os.environ.get("VLLM_API_KEY"),
            "model": os.environ.get("VLLM_MODEL"),
            "structured_mode": os.environ.get("VLLM_STRUCTURED_MODE"),
        }

        values: dict[str, Any] = {}
        for field in cls.model_fields:
            if field in cli:
                values[field] = cli[field]
            elif field in toml:
                values[field] = toml[field]
            elif env.get(field) is not None:
                values[field] = env[field]

        if not values.get("model"):
            raise ValueError("no model configured; set VLLM_MODEL, [vllm].model, or --model")
        return cls(**values)

    @classmethod
    def from_env(cls, **overrides: Any) -> "VLLMConfig":
        """Build a config from environment variables with optional overrides."""
        return cls.from_sources(cli=overrides)


class ExtractionError(RuntimeError):
    """Raised when the server response cannot be parsed into the target schema."""


def build_messages(
    text: str,
    source: Optional[SourceDocument] = None,
    focus: Optional[str] = None,
    max_input_chars: int = 120_000,
) -> list[dict[str, str]]:
    """Build the chat messages sent to the model."""
    clipped = text[:max_input_chars]
    source_desc = source.model_dump_json(exclude_none=True) if source else "{}"
    user = USER_TEMPLATE.format(
        focus=focus or "all molecules described in the article",
        source=source_desc,
        schema=json.dumps(json_schema(), indent=2),
        text=clipped,
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def parse_response(content: str) -> MolecularMetadata:
    """Parse a model response into a validated :class:`MolecularMetadata`."""
    if content is None:
        raise ExtractionError("model returned an empty response")
    cleaned = _FENCE_RE.sub("", content.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"model response is not valid JSON: {exc}") from exc
    try:
        return MolecularMetadata.model_validate(data)
    except Exception as exc:  # noqa: BLE001 - pydantic ValidationError
        raise ExtractionError(f"model JSON does not match the schema: {exc}") from exc


class VLLMExtractor:
    """Call a remote vLLM server to extract metadata from article text."""

    def __init__(self, config: VLLMConfig, client: Any = None) -> None:
        self.config = config
        if client is None:
            from openai import OpenAI

            client = OpenAI(
                base_url=config.base_url,
                api_key=config.api_key,
                timeout=config.timeout,
            )
        self.client = client

    def _structured_kwargs(self) -> dict[str, Any]:
        schema = json_schema()
        if self.config.structured_mode == "response_format":
            return {
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "MolecularMetadata",
                        "schema": schema,
                        "strict": True,
                    },
                }
            }
        return {"extra_body": {"guided_json": schema}}

    def extract(
        self,
        text: str,
        source: Optional[SourceDocument] = None,
        focus: Optional[str] = None,
    ) -> MolecularMetadata:
        """Extract metadata from one article full text."""
        messages = build_messages(
            text, source=source, focus=focus, max_input_chars=self.config.max_input_chars
        )
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "max_tokens": self.config.max_tokens,
            **self._structured_kwargs(),
        }
        if self.config.seed is not None:
            kwargs["seed"] = self.config.seed

        response = self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        return parse_response(content)


def extract_batch(
    items: Sequence[tuple[str, str, Optional[SourceDocument]]],
    extractor: VLLMExtractor,
    focus: Optional[str] = None,
) -> list[MolecularMetadata]:
    """Extract metadata for several ``(id, text, source)`` items sequentially."""
    return [
        extractor.extract(text, source=source, focus=focus)
        for _, text, source in items
    ]
