"""Tests for TOML configuration loading and precedence."""

import pytest

from lit2mol.config import (
    RunConfig,
    build_run_config,
    discover_config,
    load_toml_config,
)
from lit2mol.vllm import VLLMConfig


def write_toml(tmp_path, text: str):
    path = tmp_path / "lit2mol.toml"
    path.write_text(text)
    return path


# --------------------------------------------------------------------------- #
# Loading and discovery
# --------------------------------------------------------------------------- #


def test_load_toml_config(tmp_path):
    path = write_toml(
        tmp_path,
        """
        [vllm]
        model = "nvidia/model"
        base_url = "http://gpu:8000/v1"

        [extraction]
        paths = ["refs/fulltext"]
        concurrency = 8
        """,
    )
    data = load_toml_config(path)
    assert data["vllm"]["model"] == "nvidia/model"
    assert data["extraction"]["paths"] == ["refs/fulltext"]
    assert data["extraction"]["concurrency"] == 8


def test_discover_config_explicit(tmp_path):
    path = write_toml(tmp_path, "[vllm]\nmodel = 'm'\n")
    assert discover_config(str(path)) == path


def test_discover_config_explicit_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        discover_config(str(tmp_path / "nope.toml"))


def test_discover_config_default_when_present(tmp_path, monkeypatch):
    path = tmp_path / "lit2mol.toml"
    path.write_text("[vllm]\nmodel = 'm'\n")
    monkeypatch.chdir(tmp_path)
    assert discover_config(None) == path


def test_discover_config_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert discover_config(None) is None


# --------------------------------------------------------------------------- #
# RunConfig merging
# --------------------------------------------------------------------------- #


def test_build_run_config_defaults():
    run = build_run_config({})
    assert run == RunConfig()
    assert run.out_dir == "outputs"
    assert run.concurrency == 4


def test_build_run_config_from_toml():
    run = build_run_config(
        {},
        {"paths": ["a.txt"], "focus": "PheS", "out_dir": "out", "concurrency": 8},
    )
    assert run.paths == ["a.txt"]
    assert run.focus == "PheS"
    assert run.out_dir == "out"
    assert run.concurrency == 8


def test_build_run_config_cli_overrides_toml():
    run = build_run_config(
        {"focus": "PntAB", "concurrency": 2},
        {"focus": "PheS", "out_dir": "out", "concurrency": 8},
    )
    assert run.focus == "PntAB"
    assert run.concurrency == 2
    assert run.out_dir == "out"


def test_build_run_config_unknown_key_raises():
    with pytest.raises(ValueError, match="unknown \\[extraction\\] keys"):
        build_run_config({}, {"nope": 1})


# --------------------------------------------------------------------------- #
# VLLMConfig precedence: CLI > TOML > env > default
# --------------------------------------------------------------------------- #


def test_vllm_from_sources_cli_beats_toml_and_env(monkeypatch):
    monkeypatch.setenv("VLLM_MODEL", "from-env")
    cfg = VLLMConfig.from_sources(
        cli={"model": "from-cli"},
        toml={"model": "from-toml", "base_url": "http://toml/v1"},
    )
    assert cfg.model == "from-cli"
    assert cfg.base_url == "http://toml/v1"


def test_vllm_from_sources_toml_beats_env(monkeypatch):
    monkeypatch.setenv("VLLM_MODEL", "from-env")
    monkeypatch.setenv("VLLM_BASE_URL", "http://env/v1")
    cfg = VLLMConfig.from_sources(toml={"model": "from-toml"})
    assert cfg.model == "from-toml"
    assert cfg.base_url == "http://env/v1"


def test_vllm_from_sources_uses_env(monkeypatch):
    monkeypatch.setenv("VLLM_MODEL", "from-env")
    cfg = VLLMConfig.from_sources()
    assert cfg.model == "from-env"


def test_vllm_from_sources_defaults():
    cfg = VLLMConfig.from_sources(cli={"model": "m"})
    assert cfg.base_url == "http://localhost:8000/v1"
    assert cfg.api_key == "EMPTY"
    assert cfg.structured_mode == "guided_json"


def test_vllm_from_sources_requires_model(monkeypatch):
    monkeypatch.delenv("VLLM_MODEL", raising=False)
    with pytest.raises(ValueError, match="no model configured"):
        VLLMConfig.from_sources()


def test_vllm_from_sources_unknown_key_raises():
    with pytest.raises(ValueError, match="unknown \\[vllm\\] keys"):
        VLLMConfig.from_sources(cli={"model": "m"}, toml={"nope": 1})
