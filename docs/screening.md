# Protein-complex screening with TypeSafe

Before running the vLLM extraction, articles can be screened for whether they
describe a protein complex at all. The screen uses
[TypeSafe](https://docs.typesafe.ai/)'s System One model Jev, which answers
typed questions with calibrated probabilities instead of generated text, so a
full text is screened in one fast request (about 5k input tokens for a typical
article).

## How it works

```
 PMCxxxx.xml ──► load_article() ──► paragraphs P000, P001, …
                                         │  (chunked to fit the request budget)
                                         ▼
                           POST /v1/systemone  (Jev)
                  ┌──────────────────────┼─────────────────────────┐
     multi_protein_complex   protein_containing_complex   evidence (Choice over
            (Noul)                     (Noul)             paragraph ids + "none")
                                 focus_described (Noul, only with a focus)
                                         │
                                         ▼
                        ComplexScreen ──► outputs/screen/<id>.json
```

| Field | Question |
| --- | --- |
| `multi_protein_complex` | Probability the article describes an assembly of two or more polypeptide chains (heterodimer, multi-subunit enzyme, …). A single protein, a protein–small-molecule complex, or a list of proteins never said to associate does not count. |
| `protein_containing_complex` | Same, but also counting ribonucleoprotein and protein–nucleic-acid complexes such as the ribosome or EF-Tu·GTP·aminoacyl-tRNA. |
| `focus_described` | Probability the configured `focus` complex is a subject of the article rather than a passing mention (only when a focus is set). |
| `evidence` | Paragraph that most clearly describes a multi-protein complex, with its Choice probability and text. |

The two definitions are kept separate on purpose: the ribosome technically
qualifies as a multi-protein assembly, so papers about translation score high
on both. Use `focus_described` when you care about one specific complex.

Articles longer than `max_chunk_chars` (default 80,000 characters, well under
Jev's 32k-token state limit) are split into paragraph chunks. Each probability
is the maximum over chunks, and the evidence paragraph is the highest-scoring
one across chunks; paragraph ids stay global to the article.

Modules:

| Module | Responsibility |
| --- | --- |
| `lit2mol/typesafe.py` | `TypeSafeConfig`, `load_article` (JATS XML / txt), chunking, questions, `ComplexScreener`, `ComplexScreen` |
| `lit2mol/screen.py` | CLI and concurrent batch orchestration (`run_screen`) |

## Setup

Install the dependencies (`typesafe-sdk` is in `requirements.txt`) and create an
API key in the [TypeSafe console](https://console.typesafe.ai/):

```bash
uv pip install --python .venv/bin/python -r requirements.txt
export TYPESAFE_API_KEY=...
```

Keep the key in the environment rather than in a committed file.

## Running

```bash
# every refs/fulltext/*.xml -> outputs/screen/<id>.json
.venv/bin/python -m lit2mol.screen refs/fulltext

# also check for a specific complex
.venv/bin/python -m lit2mol.screen refs/fulltext \
  --focus "phenylalanyl-tRNA synthetase (PheS/PheT)" --out-dir outputs/screen/phes
```

The screen reads PMC JATS `.xml` files by default because the `.txt` files in
`refs/fulltext` may contain only the abstract. Plain `.txt` files also work
(`--pattern '*.txt'`): the first non-empty line is the title and every other
non-empty line is a paragraph.

Or configure it in `lit2mol.toml` alongside the extraction settings:

```toml
[typesafe]
model = "jev-latest"      # pin e.g. "jev-1.13.0" once thresholds are tuned
# api_key: prefer the TYPESAFE_API_KEY environment variable

[screen]
paths = ["refs/fulltext"]
focus = "phenylalanyl-tRNA synthetase (PheS/PheT)"
out_dir = "outputs/screen/phes"
concurrency = 8
```

```bash
.venv/bin/python -m lit2mol.screen --config lit2mol.toml
```

Exit codes match the extraction CLI: `0` all files succeeded, `1` any file
failed, `2` configuration error or no input files.

## Configuration reference

Precedence, highest first: command-line flags, TOML file, environment
variables, built-in defaults.

`[typesafe]` settings:

| Setting | Flag | TOML key | Environment variable | Default |
| --- | --- | --- | --- | --- |
| API key | `--api-key` | `api_key` | `TYPESAFE_API_KEY` | none (required) |
| Model | `--model` | `model` | `TYPESAFE_MODEL` | `jev-latest` |
| Request timeout | `--timeout` | `timeout` | | `120` |
| Chunk size (chars) | `--max-chunk-chars` | `max_chunk_chars` | | `80000` |

`[screen]` settings use the same keys as `[extraction]` with different defaults:

| Setting | Flag | TOML key | Default |
| --- | --- | --- | --- |
| Input files/dirs | positional `paths` | `paths` | none |
| Focus | `--focus` | `focus` | none |
| Output directory | `--out-dir` | `out_dir` | `outputs/screen` |
| Directory glob | `--pattern` | `pattern` | `*.xml` |
| Limit | `--limit` | `limit` | none |
| Concurrency | `--concurrency` | `concurrency` | `4` |

## Output

```json
{
  "source": {"pmcid": "PMC6640638", "title": "In Vivo Biosynthesis of a β-Amino Acid-Containing Protein"},
  "model": "jev-1.13.0",
  "multi_protein_complex": 0.82,
  "protein_containing_complex": 0.98,
  "focus": "phenylalanyl-tRNA synthetase (PheS/PheT)",
  "focus_described": 0.91,
  "evidence": {"paragraph_id": "P007", "probability": 0.93, "text": "Once aminoacylated, tRNAs are delivered to the ribosome by the translation factor EF-Tu in complex with GTP. …"},
  "paragraphs": 23,
  "chunks": 1,
  "input_tokens": 5059
}
```

Choose thresholds (for example, which articles go on to extraction) on
articles you have labelled; the probabilities are calibrated, but the right
cut-off depends on the cost of missing a paper versus extracting an irrelevant
one.

## Programmatic use

```python
from pathlib import Path

from lit2mol.extract import source_for
from lit2mol.typesafe import ComplexScreener, TypeSafeConfig, load_article

screener = ComplexScreener(TypeSafeConfig.from_sources())   # TYPESAFE_API_KEY from env
path = Path("refs/fulltext/PMC6640638.xml")
result = screener.screen(load_article(path), source=source_for(path), focus="PheRS")
print(result.multi_protein_complex, result.evidence)
```

## Testing without the API

`tests/test_screen.py` uses a fake TypeSafe client, so no key or network is
needed:

```bash
.venv/bin/pytest -q tests/test_screen.py
```
