"""Protein-complex screening of full texts with TypeSafe's System One API.

Before running the (slow, expensive) vLLM extraction, each article can be
screened for whether it describes a protein complex at all. The screen asks
TypeSafe's Jev model typed questions over the article's paragraphs and returns
calibrated probabilities instead of generated text:

- ``multi_protein_complex`` — an assembly of two or more polypeptide chains
- ``protein_containing_complex`` — any complex containing protein, including
  ribonucleoproteins such as the ribosome and EF-Tu·GTP·aminoacyl-tRNA
- ``focus_described`` — the configured focus complex (only when a focus is set)
- ``evidence`` — the paragraph that most clearly describes a multi-protein complex

Long articles are split into paragraph chunks that fit the request budget; each
probability is the maximum over chunks (the article describes a complex if any
part of it does).
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional, Sequence

from pydantic import BaseModel, Field

from lit2mol.schema import SourceDocument, StrictModel

DEFAULT_MODEL = "jev-latest"

# Choice questions accept at most 255 options; one is reserved for "none".
MAX_CHUNK_PARAGRAPHS = 254

MULTI_PROTEIN_DEFINITION = (
    "A protein complex is a stable or functional assembly of two or more "
    "polypeptide chains (e.g. a heterodimer, a multi-subunit enzyme, a receptor "
    "bound to its protein partner). A single protein, a protein bound only to a "
    "small molecule, or a mere list of proteins that are never said to associate "
    "does not count."
)
PROTEIN_CONTAINING_DEFINITION = (
    f"{MULTI_PROTEIN_DEFINITION} In addition, count any macromolecular complex "
    "containing protein, including ribonucleoprotein assemblies such as the "
    "ribosome or ribosomal subunits, and protein-nucleic acid complexes such as "
    "EF-Tu·GTP·aminoacyl-tRNA."
)


class TypeSafeConfig(BaseModel):
    """Connection settings for the TypeSafe System One API."""

    api_key: str
    model: str = DEFAULT_MODEL
    timeout: float = Field(default=120.0, gt=0)
    max_chunk_chars: int = Field(default=80_000, gt=0)

    @classmethod
    def from_sources(
        cls,
        cli: Optional[dict[str, Any]] = None,
        toml: Optional[dict[str, Any]] = None,
    ) -> "TypeSafeConfig":
        """Build a config from CLI args, a TOML table, and environment variables.

        Precedence: non-``None`` CLI values, then TOML values, then environment
        variables (``TYPESAFE_API_KEY``, ``TYPESAFE_MODEL``), then field defaults.
        """
        cli = {k: v for k, v in (cli or {}).items() if v is not None}
        toml = dict(toml or {})

        unknown = set(toml) - set(cls.model_fields)
        if unknown:
            raise ValueError(f"unknown [typesafe] keys: {sorted(unknown)}")

        env = {
            "api_key": os.environ.get("TYPESAFE_API_KEY"),
            "model": os.environ.get("TYPESAFE_MODEL"),
        }

        values: dict[str, Any] = {}
        for field in cls.model_fields:
            if field in cli:
                values[field] = cli[field]
            elif field in toml:
                values[field] = toml[field]
            elif env.get(field) is not None:
                values[field] = env[field]

        if not values.get("api_key"):
            raise ValueError(
                "no TypeSafe API key configured; set TYPESAFE_API_KEY, "
                "[typesafe].api_key, or --api-key"
            )
        return cls(**values)


class Article(StrictModel):
    """Title and paragraphs of one full text."""

    title: Optional[str] = None
    paragraphs: list[str] = Field(default_factory=list)


def _clean(element: ET.Element) -> str:
    return " ".join("".join(element.itertext()).split())


def load_article(path: Path) -> Article:
    """Read a PMC JATS ``.xml`` file (abstract + body) or a plain ``.txt`` file.

    For ``.txt`` files the first non-empty line is the title and every other
    non-empty line is a paragraph.
    """
    path = Path(path)
    if path.suffix.lower() == ".xml":
        root = ET.parse(path).getroot()
        article = root if root.tag == "article" else root.find(".//article")
        if article is None:
            raise ValueError(f"no <article> element in {path}")
        title_el = article.find(".//front//article-title")
        paragraphs: list[str] = []
        for section in (article.find(".//front//abstract"), article.find("body")):
            if section is not None:
                paragraphs += [_clean(p) for p in section.iter("p")]
        return Article(
            title=_clean(title_el) if title_el is not None else None,
            paragraphs=[p for p in paragraphs if p],
        )

    lines = [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return Article()
    return Article(title=lines[0], paragraphs=lines[1:])


def paragraph_id(index: int) -> str:
    return f"P{index:03d}"


def chunk_paragraphs(
    paragraphs: Sequence[str],
    max_chars: int,
    max_items: int = MAX_CHUNK_PARAGRAPHS,
) -> list[dict[str, str]]:
    """Split paragraphs into ``{paragraph_id: text}`` chunks within the budget.

    Ids are global to the article so evidence can be traced back. A single
    paragraph longer than ``max_chars`` is truncated.
    """
    chunks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    size = 0
    for index, text in enumerate(paragraphs):
        text = text[:max_chars]
        if current and (size + len(text) > max_chars or len(current) >= max_items):
            chunks.append(current)
            current, size = {}, 0
        current[paragraph_id(index)] = text
        size += len(text)
    if current:
        chunks.append(current)
    return chunks


def build_questions(paragraph_ids: Sequence[str], focus: Optional[str] = None) -> dict[str, dict]:
    """Build the TypeSafe questions asked of every chunk."""
    questions: dict[str, dict] = {
        "multi_protein_complex": {
            "type": "noul",
            "instructions": {
                "protein_complex_definition": MULTI_PROTEIN_DEFINITION,
                "question": "Does the article in `paragraphs` describe a protein "
                "complex as defined in `protein_complex_definition`, for example "
                "its composition, formation, structure, or function?",
            },
            "criteria": {
                "true": "The article describes at least one assembly of two or "
                "more polypeptide chains.",
                "false": "No multi-protein assembly is described.",
            },
        },
        "protein_containing_complex": {
            "type": "noul",
            "instructions": {
                "definition": PROTEIN_CONTAINING_DEFINITION,
                "question": "Does the article in `paragraphs` describe a complex "
                "that contains protein, as defined in `definition`?",
            },
            "criteria": {
                "true": "The article describes at least one protein-containing complex.",
                "false": "No protein-containing complex is described.",
            },
        },
        "evidence": {
            "type": "choice",
            "instructions": {
                "protein_complex_definition": MULTI_PROTEIN_DEFINITION,
                "question": "Which paragraph in `paragraphs` most clearly describes "
                "a protein complex as defined in `protein_complex_definition`? "
                "Choose `none` if no paragraph does.",
            },
            "criteria": {
                "none": "No paragraph describes a protein complex.",
                **{pid: None for pid in paragraph_ids},
            },
        },
    }
    if focus:
        questions["focus_described"] = {
            "type": "noul",
            "instructions": {
                "focus": focus,
                "question": "Does the article in `paragraphs` describe `focus` "
                "(its subunits, assembly, structure, activity, or regulation), "
                "rather than only mentioning it in passing?",
            },
            "criteria": {
                "true": "`focus` is a subject of the article.",
                "false": "`focus` is absent or only mentioned in passing.",
            },
        }
    return questions


class ScreenEvidence(StrictModel):
    """The paragraph that most clearly describes a multi-protein complex."""

    paragraph_id: str
    probability: float = Field(ge=0.0, le=1.0)
    text: str


class ComplexScreen(StrictModel):
    """Result of screening one article for protein complexes."""

    source: SourceDocument
    model: str
    multi_protein_complex: float = Field(ge=0.0, le=1.0)
    protein_containing_complex: float = Field(ge=0.0, le=1.0)
    focus: Optional[str] = None
    focus_described: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    evidence: Optional[ScreenEvidence] = None
    paragraphs: int = Field(ge=0)
    chunks: int = Field(ge=0)
    input_tokens: int = Field(default=0, ge=0)


class ScreenError(RuntimeError):
    """Raised when an article cannot be screened."""


class ComplexScreener:
    """Screen articles for protein complexes with TypeSafe."""

    def __init__(self, config: TypeSafeConfig, client: Any = None) -> None:
        self.config = config
        if client is None:
            from typesafe_sdk import TypeSafeClient

            client = TypeSafeClient(api_key=config.api_key, timeout=config.timeout)
        self.client = client

    def screen(
        self,
        article: Article,
        source: Optional[SourceDocument] = None,
        focus: Optional[str] = None,
    ) -> ComplexScreen:
        """Screen one article; probabilities are the maximum over chunks."""
        if not article.paragraphs:
            raise ScreenError("article has no paragraphs")
        source = source or SourceDocument()
        if article.title and source.title is None:
            source = source.model_copy(update={"title": article.title})

        chunks = chunk_paragraphs(article.paragraphs, self.config.max_chunk_chars)
        multi = protein = 0.0
        focus_p: Optional[float] = 0.0 if focus else None
        evidence: Optional[ScreenEvidence] = None
        input_tokens = 0
        model = self.config.model

        for chunk in chunks:
            response = self.client.system_one(
                state={"title": article.title, "paragraphs": chunk},
                questions=build_questions(list(chunk), focus=focus),
                model=self.config.model,
            )
            answers = response.answers
            model = response.model
            input_tokens += getattr(response.usage, "input_tokens", 0) or 0
            multi = max(multi, answers["multi_protein_complex"].noul)
            protein = max(protein, answers["protein_containing_complex"].noul)
            if focus:
                focus_p = max(focus_p, answers["focus_described"].noul)
            for pid, prob in answers["evidence"].probabilities.items():
                if pid != "none" and pid in chunk and (evidence is None or prob > evidence.probability):
                    evidence = ScreenEvidence(paragraph_id=pid, probability=prob, text=chunk[pid])

        return ComplexScreen(
            source=source,
            model=model,
            multi_protein_complex=multi,
            protein_containing_complex=protein,
            focus=focus,
            focus_described=focus_p,
            evidence=evidence,
            paragraphs=len(article.paragraphs),
            chunks=len(chunks),
            input_tokens=input_tokens,
        )
