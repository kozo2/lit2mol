"""Tests for the remote vLLM extraction client."""

import json
from types import SimpleNamespace

import pytest

from lit2mol.schema import Gene, MolecularMetadata, SourceDocument, json_schema
from lit2mol.vllm import (
    ExtractionError,
    VLLMConfig,
    VLLMExtractor,
    build_messages,
    parse_response,
)


def sample_doc() -> MolecularMetadata:
    return MolecularMetadata(
        source=SourceDocument(pmcid="PMC1234567"),
        genes=[Gene(id="pheS", name="pheS", locus_tag="b1717")],
    )


def make_client(content: str) -> tuple[SimpleNamespace, dict]:
    """Build a fake OpenAI client and a dict that captures the request kwargs."""
    captured: dict = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return client, captured


def config(**overrides) -> VLLMConfig:
    values = {"model": "test-model", "max_input_chars": 1000}
    values.update(overrides)
    return VLLMConfig(**values)


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #


def test_build_messages_includes_schema_focus_and_text():
    messages = build_messages("ARTICLE BODY", SourceDocument(pmcid="PMC1234567"), focus="PheS")
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    user = messages[1]["content"]
    assert "PheS" in user
    assert "ARTICLE BODY" in user
    assert '"MolecularMetadata"' in user
    assert "PMC1234567" in user


def test_build_messages_truncates_long_text():
    messages = build_messages("x" * 5000, max_input_chars=100)
    assert "x" * 100 in messages[1]["content"]
    assert "x" * 101 not in messages[1]["content"]


def test_build_messages_defaults_focus():
    messages = build_messages("body")
    assert "all molecules" in messages[1]["content"]


# --------------------------------------------------------------------------- #
# Response parsing
# --------------------------------------------------------------------------- #


def test_parse_response_accepts_plain_json():
    doc = parse_response(sample_doc().model_dump_json())
    assert doc.genes[0].id == "pheS"


def test_parse_response_strips_markdown_fences():
    payload = "```json\n" + sample_doc().model_dump_json() + "\n```"
    assert parse_response(payload).source.pmcid == "PMC1234567"


def test_parse_response_rejects_invalid_json():
    with pytest.raises(ExtractionError, match="not valid JSON"):
        parse_response("this is not json")


def test_parse_response_rejects_schema_mismatch():
    with pytest.raises(ExtractionError, match="does not match the schema"):
        parse_response('{"source": {}, "monomers": [{"id": "M", "name": "m", "gene_ref": "x"}]}')


def test_parse_response_rejects_empty():
    with pytest.raises(ExtractionError, match="empty response"):
        parse_response(None)


# --------------------------------------------------------------------------- #
# VLLMExtractor
# --------------------------------------------------------------------------- #


def test_extract_returns_validated_model_with_guided_json():
    client, captured = make_client(sample_doc().model_dump_json())
    extractor = VLLMExtractor(config(), client=client)

    doc = extractor.extract("body", source=SourceDocument(pmcid="PMC1234567"), focus="PheS")

    assert doc == sample_doc()
    assert captured["model"] == "test-model"
    assert captured["temperature"] == 0.0
    assert captured["extra_body"]["guided_json"] == json_schema()
    assert "response_format" not in captured


def test_extract_uses_response_format_mode():
    client, captured = make_client(sample_doc().model_dump_json())
    extractor = VLLMExtractor(config(structured_mode="response_format"), client=client)

    extractor.extract("body")

    response_format = captured["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "MolecularMetadata"
    assert response_format["json_schema"]["schema"] == json_schema()
    assert "extra_body" not in captured


def test_extract_passes_seed_when_set():
    client, captured = make_client(sample_doc().model_dump_json())
    extractor = VLLMExtractor(config(seed=123), client=client)
    extractor.extract("body")
    assert captured["seed"] == 123


def test_extract_raises_on_garbage_response():
    client, _ = make_client("not json at all")
    extractor = VLLMExtractor(config(), client=client)
    with pytest.raises(ExtractionError):
        extractor.extract("body")


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("VLLM_BASE_URL", "http://gpu:9000/v1")
    monkeypatch.setenv("VLLM_API_KEY", "secret")
    monkeypatch.setenv("VLLM_MODEL", "nvidia/model")
    monkeypatch.setenv("VLLM_STRUCTURED_MODE", "response_format")

    cfg = VLLMConfig.from_env()

    assert cfg.base_url == "http://gpu:9000/v1"
    assert cfg.api_key == "secret"
    assert cfg.model == "nvidia/model"
    assert cfg.structured_mode == "response_format"


def test_config_from_env_overrides(monkeypatch):
    monkeypatch.setenv("VLLM_MODEL", "from-env")
    cfg = VLLMConfig.from_env(model="from-arg", base_url="http://other/v1")
    assert cfg.model == "from-arg"
    assert cfg.base_url == "http://other/v1"


def test_config_from_env_requires_model(monkeypatch):
    monkeypatch.delenv("VLLM_MODEL", raising=False)
    with pytest.raises(ValueError, match="no model configured"):
        VLLMConfig.from_env()
