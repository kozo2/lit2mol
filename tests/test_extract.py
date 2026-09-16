"""Tests for the extraction CLI and batch orchestration (no network)."""

import json
from pathlib import Path

import pytest

from lit2mol.extract import (
    collect_input_files,
    document_id,
    main,
    run_batch,
    source_for,
)
from lit2mol.schema import Gene, MolecularMetadata, SourceDocument
from lit2mol.vllm import ExtractionError


def sample_doc(pmcid: str = "PMC1234567") -> MolecularMetadata:
    return MolecularMetadata(
        source=SourceDocument(pmcid=pmcid),
        genes=[Gene(id="pheS", name="pheS")],
    )


class StubExtractor:
    """Minimal stand-in for :class:`VLLMExtractor`."""

    def __init__(self, doc: MolecularMetadata | None = None, error: Exception | None = None):
        self.doc = doc or sample_doc()
        self.error = error
        self.calls: list[tuple] = []

    def extract(self, text, source=None, focus=None):
        self.calls.append((text, source, focus))
        if self.error is not None:
            raise self.error
        return self.doc


# --------------------------------------------------------------------------- #
# File collection and ids
# --------------------------------------------------------------------------- #


def test_collect_input_files_expands_directories(tmp_path):
    (tmp_path / "PMC1.txt").write_text("a")
    (tmp_path / "PMC2.txt").write_text("b")
    (tmp_path / "refs.csv").write_text("c")

    files = collect_input_files([str(tmp_path)])

    assert [f.name for f in files] == ["PMC1.txt", "PMC2.txt"]


def test_collect_input_files_dedupes(tmp_path):
    file = tmp_path / "PMC1.txt"
    file.write_text("a")
    files = collect_input_files([str(file), str(file), str(tmp_path)])
    assert len(files) == 1


def test_collect_input_files_accepts_explicit_files(tmp_path):
    file = tmp_path / "custom.txt"
    file.write_text("a")
    assert collect_input_files([str(file)])[0] == file


def test_document_id_uses_stem():
    assert document_id(Path("/x/PMC1234567.txt")) == "PMC1234567"


def test_source_for_pmcid():
    assert source_for(Path("PMC1234567.txt")).pmcid == "PMC1234567"
    assert source_for(Path("PMC1234567.txt")).pmid is None


def test_source_for_non_pmcid_is_empty():
    assert source_for(Path("notes.txt")).pmcid is None


# --------------------------------------------------------------------------- #
# run_batch
# --------------------------------------------------------------------------- #


def test_run_batch_writes_validated_json(tmp_path):
    src = tmp_path / "PMC1.txt"
    src.write_text("article body")
    out = tmp_path / "out"
    extractor = StubExtractor(doc=sample_doc("PMC1"))

    results = run_batch([src], extractor, out, focus="PheS")

    assert len(results) == 1
    assert results[0].ok
    written = json.loads((out / "PMC1.json").read_text())
    assert written["genes"][0]["id"] == "pheS"
    assert extractor.calls[0][2] == "PheS"
    assert extractor.calls[0][1].pmcid == "PMC1"


def test_run_batch_records_errors(tmp_path):
    src = tmp_path / "PMC1.txt"
    src.write_text("body")
    extractor = StubExtractor(error=ExtractionError("boom"))

    results = run_batch([src], extractor, tmp_path / "out")

    assert results[0].ok is False
    assert "boom" in results[0].error
    assert not (tmp_path / "out" / "PMC1.json").exists()


def test_run_batch_respects_limit(tmp_path):
    files = []
    for i in range(3):
        f = tmp_path / f"PMC{i}.txt"
        f.write_text("body")
        files.append(f)
    extractor = StubExtractor()

    results = run_batch(files, extractor, tmp_path / "out", limit=2)

    assert len(results) == 2
    assert len(extractor.calls) == 2


def test_run_batch_preserves_input_order_with_concurrency(tmp_path):
    files = []
    for i in range(5):
        f = tmp_path / f"PMC{i}.txt"
        f.write_text(f"body {i}")
        files.append(f)
    extractor = StubExtractor()

    results = run_batch(files, extractor, tmp_path / "out", concurrency=4)

    assert [r.input_path for r in results] == files


# --------------------------------------------------------------------------- #
# CLI main
# --------------------------------------------------------------------------- #


def test_main_writes_outputs(tmp_path, monkeypatch):
    src_dir = tmp_path / "fulltext"
    src_dir.mkdir()
    (src_dir / "PMC111.txt").write_text("body one")
    (src_dir / "PMC222.txt").write_text("body two")
    out_dir = tmp_path / "out"

    stub = StubExtractor()

    def factory(config):
        return stub

    monkeypatch.setattr("lit2mol.extract.VLLMExtractor", factory)
    code = main(
        [
            str(src_dir),
            "--out-dir",
            str(out_dir),
            "--focus",
            "PheS",
            "--model",
            "test-model",
        ]
    )

    assert code == 0
    assert sorted(p.name for p in out_dir.glob("*.json")) == ["PMC111.json", "PMC222.json"]


def test_main_returns_nonzero_on_failure(tmp_path, monkeypatch):
    src = tmp_path / "PMC111.txt"
    src.write_text("body")
    monkeypatch.setattr(
        "lit2mol.extract.VLLMExtractor",
        lambda config: StubExtractor(error=ExtractionError("nope")),
    )
    code = main([str(src), "--out-dir", str(tmp_path / "out"), "--model", "m"])
    assert code == 1


def test_main_returns_two_when_no_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr("lit2mol.extract.VLLMExtractor", lambda config: StubExtractor())
    empty = tmp_path / "empty"
    empty.mkdir()
    code = main([str(empty), "--out-dir", str(tmp_path / "out"), "--model", "m"])
    assert code == 2


# --------------------------------------------------------------------------- #
# CLI main driven by a TOML config file
# --------------------------------------------------------------------------- #


def write_config(tmp_path, text: str) -> Path:
    path = tmp_path / "lit2mol.toml"
    path.write_text(text)
    return path


def test_main_uses_toml_config(tmp_path, monkeypatch):
    src_dir = tmp_path / "fulltext"
    src_dir.mkdir()
    (src_dir / "PMC1.txt").write_text("body")
    config_path = write_config(
        tmp_path,
        f"""
        [extraction]
        paths = ["{src_dir}"]
        focus = "PheS"
        out_dir = "{tmp_path / 'out'}"
        concurrency = 2

        [vllm]
        base_url = "http://toml-host:8000/v1"
        api_key = "secret"
        model = "toml-model"
        """,
    )

    captured = {}
    stub = StubExtractor()

    def factory(config):
        captured["config"] = config
        return stub

    monkeypatch.setattr("lit2mol.extract.VLLMExtractor", factory)
    code = main(["--config", str(config_path)])

    assert code == 0
    assert (tmp_path / "out" / "PMC1.json").exists()
    assert captured["config"].model == "toml-model"
    assert captured["config"].base_url == "http://toml-host:8000/v1"
    assert captured["config"].api_key == "secret"
    assert stub.calls[0][2] == "PheS"


def test_main_cli_overrides_toml(tmp_path, monkeypatch):
    src = tmp_path / "PMC1.txt"
    src.write_text("body")
    config_path = write_config(
        tmp_path,
        """
        [extraction]
        focus = "PheS"

        [vllm]
        model = "toml-model"
        """,
    )

    captured = {}
    stub = StubExtractor()

    def factory(config):
        captured["config"] = config
        return stub

    monkeypatch.setattr("lit2mol.extract.VLLMExtractor", factory)
    code = main(
        [
            str(src),
            "--config",
            str(config_path),
            "--model",
            "cli-model",
            "--focus",
            "PntAB",
            "--out-dir",
            str(tmp_path / "out"),
        ]
    )

    assert code == 0
    assert captured["config"].model == "cli-model"
    assert stub.calls[0][2] == "PntAB"


def test_main_auto_discovers_default_config(tmp_path, monkeypatch):
    src_dir = tmp_path / "fulltext"
    src_dir.mkdir()
    (src_dir / "PMC1.txt").write_text("body")
    write_config(
        tmp_path,
        """
        [extraction]
        paths = ["fulltext"]
        out_dir = "out"

        [vllm]
        model = "auto-model"
        """,
    )
    captured = {}

    def factory(config):
        captured["config"] = config
        return StubExtractor()

    monkeypatch.setattr("lit2mol.extract.VLLMExtractor", factory)
    monkeypatch.chdir(tmp_path)
    code = main([])

    assert code == 0
    assert captured["config"].model == "auto-model"
    assert (tmp_path / "out" / "PMC1.json").exists()


def test_main_invalid_toml_key_returns_two(tmp_path, monkeypatch):
    src = tmp_path / "PMC1.txt"
    src.write_text("body")
    config_path = write_config(
        tmp_path,
        """
        [extraction]
        nope = 1

        [vllm]
        model = "m"
        """,
    )
    monkeypatch.setattr("lit2mol.extract.VLLMExtractor", lambda config: StubExtractor())
    code = main([str(src), "--config", str(config_path)])
    assert code == 2
