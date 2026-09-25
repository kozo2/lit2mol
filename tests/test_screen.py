"""Tests for the TypeSafe protein-complex screen (no network)."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lit2mol.config import build_run_config
from lit2mol.schema import SourceDocument
from lit2mol.screen import main, run_screen
from lit2mol.typesafe import (
    Article,
    ComplexScreener,
    ScreenError,
    TypeSafeConfig,
    build_questions,
    chunk_paragraphs,
    load_article,
)

JATS = """<?xml version="1.0"?>
<pmc-articleset><article>
  <front><article-meta>
    <title-group><article-title>PheRS <italic>in vivo</italic></article-title></title-group>
    <abstract><p>PheS and PheT form an   (&#945;&#946;)2 tetramer.</p></abstract>
  </article-meta></front>
  <body>
    <sec><title>Results</title><p>First body paragraph.</p><p></p><p>Second.</p></sec>
  </body>
  <back><ref-list><ref><mixed-citation><p>Not a paragraph.</p></mixed-citation></ref></ref-list></back>
</article></pmc-articleset>
"""


def noul(p):
    return SimpleNamespace(noul=p)


def choice(probabilities):
    return SimpleNamespace(
        choice=max(probabilities, key=probabilities.get), probabilities=probabilities
    )


class FakeClient:
    """Stand-in for ``typesafe_sdk.TypeSafeClient`` returning scripted answers."""

    def __init__(self, answers=None):
        self.answers = list(answers or [])
        self.calls: list[dict] = []

    def system_one(self, state, questions, model=None):
        self.calls.append({"state": state, "questions": questions, "model": model})
        if self.answers:
            answers = self.answers.pop(0)
        else:
            pids = [k for k in questions["evidence"]["criteria"] if k != "none"]
            answers = {
                "multi_protein_complex": noul(0.9),
                "protein_containing_complex": noul(0.95),
                "evidence": choice({"none": 0.1, pids[0]: 0.9}),
            }
            if "focus_described" in questions:
                answers["focus_described"] = noul(0.8)
        return SimpleNamespace(
            answers=answers, model="jev-test", usage=SimpleNamespace(input_tokens=100)
        )


def config(**overrides):
    return TypeSafeConfig(api_key="test-key", **overrides)


# --------------------------------------------------------------------------- #
# Article loading and chunking
# --------------------------------------------------------------------------- #


def test_load_article_xml_reads_title_abstract_and_body(tmp_path):
    path = tmp_path / "PMC1.xml"
    path.write_text(JATS)
    article = load_article(path)
    assert article.title == "PheRS in vivo"
    assert article.paragraphs == [
        "PheS and PheT form an (αβ)2 tetramer.",
        "First body paragraph.",
        "Second.",
    ]


def test_load_article_txt_uses_first_line_as_title(tmp_path):
    path = tmp_path / "PMC1.txt"
    path.write_text("Title\n\nABSTRACT\nSome text.\n")
    assert load_article(path) == Article(title="Title", paragraphs=["ABSTRACT", "Some text."])


def test_load_article_xml_without_article_raises(tmp_path):
    path = tmp_path / "bad.xml"
    path.write_text("<root/>")
    with pytest.raises(ValueError, match="no <article>"):
        load_article(path)


def test_chunk_paragraphs_respects_char_budget_and_keeps_global_ids():
    chunks = chunk_paragraphs(["a" * 6, "b" * 6, "c" * 6], max_chars=12)
    assert [list(c) for c in chunks] == [["P000", "P001"], ["P002"]]


def test_chunk_paragraphs_respects_item_limit_and_truncates():
    chunks = chunk_paragraphs(["x" * 50, "y", "z"], max_chars=10, max_items=2)
    assert chunks[0] == {"P000": "x" * 10}
    assert chunks[1] == {"P001": "y", "P002": "z"}


# --------------------------------------------------------------------------- #
# Questions
# --------------------------------------------------------------------------- #


def test_build_questions_without_focus():
    questions = build_questions(["P000", "P001"])
    assert set(questions) == {"multi_protein_complex", "protein_containing_complex", "evidence"}
    assert list(questions["evidence"]["criteria"]) == ["none", "P000", "P001"]
    assert questions["multi_protein_complex"]["type"] == "noul"


def test_build_questions_with_focus():
    questions = build_questions(["P000"], focus="PheRS")
    assert questions["focus_described"]["instructions"]["focus"] == "PheRS"


# --------------------------------------------------------------------------- #
# ComplexScreener
# --------------------------------------------------------------------------- #


def test_screen_single_chunk():
    client = FakeClient()
    screener = ComplexScreener(config(), client=client)
    article = Article(title="T", paragraphs=["p0", "p1"])

    result = screener.screen(article, source=SourceDocument(pmcid="PMC1"))

    assert result.multi_protein_complex == 0.9
    assert result.protein_containing_complex == 0.95
    assert result.focus_described is None
    assert result.evidence.paragraph_id == "P000"
    assert result.evidence.text == "p0"
    assert result.source.pmcid == "PMC1"
    assert result.source.title == "T"
    assert result.model == "jev-test"
    assert result.chunks == 1
    assert result.input_tokens == 100
    assert client.calls[0]["state"] == {"title": "T", "paragraphs": {"P000": "p0", "P001": "p1"}}
    assert client.calls[0]["model"] == "jev-latest"


def test_screen_takes_max_over_chunks():
    client = FakeClient(
        answers=[
            {
                "multi_protein_complex": noul(0.2),
                "protein_containing_complex": noul(0.9),
                "evidence": choice({"none": 0.7, "P000": 0.3}),
                "focus_described": noul(0.1),
            },
            {
                "multi_protein_complex": noul(0.6),
                "protein_containing_complex": noul(0.4),
                "evidence": choice({"none": 0.2, "P001": 0.8}),
                "focus_described": noul(0.7),
            },
        ]
    )
    screener = ComplexScreener(config(max_chunk_chars=5), client=client)

    result = screener.screen(Article(paragraphs=["aaaa", "bbbb"]), focus="PheRS")

    assert len(client.calls) == 2
    assert result.chunks == 2
    assert result.multi_protein_complex == 0.6
    assert result.protein_containing_complex == 0.9
    assert result.focus_described == 0.7
    assert result.evidence.paragraph_id == "P001"
    assert result.input_tokens == 200


def test_screen_rejects_empty_article():
    screener = ComplexScreener(config(), client=FakeClient())
    with pytest.raises(ScreenError):
        screener.screen(Article())


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def test_typesafe_config_precedence(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "env-key")
    monkeypatch.setenv("TYPESAFE_MODEL", "env-model")
    cfg = TypeSafeConfig.from_sources(cli={"model": "cli-model"}, toml={"timeout": 5.0})
    assert cfg.api_key == "env-key"
    assert cfg.model == "cli-model"
    assert cfg.timeout == 5.0


def test_typesafe_config_requires_api_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="no TypeSafe API key"):
        TypeSafeConfig.from_sources()


def test_typesafe_config_unknown_key_raises():
    with pytest.raises(ValueError, match="unknown \\[typesafe\\] keys"):
        TypeSafeConfig.from_sources(cli={"api_key": "k"}, toml={"nope": 1})


def test_build_run_config_custom_defaults_and_table():
    run = build_run_config({}, None, table="screen", defaults={"pattern": "*.xml"})
    assert run.pattern == "*.xml"
    with pytest.raises(ValueError, match="unknown \\[screen\\] keys"):
        build_run_config({}, {"nope": 1}, table="screen")


# --------------------------------------------------------------------------- #
# run_screen and CLI
# --------------------------------------------------------------------------- #


def write_articles(directory: Path, names):
    directory.mkdir(exist_ok=True)
    for name in names:
        (directory / name).write_text(JATS)


def test_run_screen_writes_json_and_preserves_order(tmp_path):
    write_articles(tmp_path / "ft", [f"PMC{i}.xml" for i in range(4)])
    files = sorted((tmp_path / "ft").glob("*.xml"))
    screener = ComplexScreener(config(), client=FakeClient())

    results = run_screen(files, screener, tmp_path / "out", focus="PheRS", concurrency=3)

    assert [r.input_path for r in results] == files
    written = json.loads((tmp_path / "out" / "PMC0.json").read_text())
    assert written["source"]["pmcid"] == "PMC0"
    assert written["focus_described"] == 0.8
    assert written["evidence"]["paragraph_id"] == "P000"


def test_run_screen_records_errors(tmp_path):
    bad = tmp_path / "PMC9.xml"
    bad.write_text("<root/>")
    screener = ComplexScreener(config(), client=FakeClient())
    results = run_screen([bad], screener, tmp_path / "out")
    assert results[0].ok is False
    assert not (tmp_path / "out" / "PMC9.json").exists()


def test_main_uses_toml_and_xml_default_pattern(tmp_path, monkeypatch):
    write_articles(tmp_path / "ft", ["PMC1.xml", "PMC2.xml"])
    (tmp_path / "ft" / "PMC1.txt").write_text("ignored\n")
    config_path = tmp_path / "lit2mol.toml"
    config_path.write_text(
        f"""
        [screen]
        paths = ["{tmp_path / 'ft'}"]
        out_dir = "{tmp_path / 'out'}"
        focus = "PheRS"

        [typesafe]
        api_key = "toml-key"
        model = "jev-pinned"
        """
    )
    captured = {}

    def factory(cfg):
        captured["config"] = cfg
        return ComplexScreener(cfg, client=FakeClient())

    monkeypatch.setattr("lit2mol.screen.ComplexScreener", factory)
    code = main(["--config", str(config_path)])

    assert code == 0
    assert captured["config"].api_key == "toml-key"
    assert captured["config"].model == "jev-pinned"
    assert sorted(p.name for p in (tmp_path / "out").glob("*.json")) == ["PMC1.json", "PMC2.json"]


def test_main_missing_api_key_returns_two(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    assert main([str(tmp_path)]) == 2


def test_main_returns_two_when_no_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "lit2mol.screen.ComplexScreener", lambda cfg: ComplexScreener(cfg, client=FakeClient())
    )
    assert main([str(tmp_path), "--out-dir", str(tmp_path / "out")]) == 2
