# LLM metadata extraction via a remote vLLM server

The extraction task is delegated to a large language model served by a remote
[vLLM](https://docs.vllm.ai/) instance. vLLM exposes an OpenAI-compatible API,
so `lit2mol` talks to it with the official `openai` client and constrains
decoding with the JSON Schema generated from `lit2mol.schema.MolecularMetadata`.

## How it works

```
 full-text .txt ──► build_messages() ──► POST /v1/chat/completions ──► vLLM
                                              (guided JSON decoding)
        │                                                              │
        └──────────────  MolecularMetadata ◄── parse_response() ◄──────┘
                        (Pydantic validated)
                                                       │
                                                       ▼
                                            outputs/<id>.json
```

Modules:

| Module | Responsibility |
| --- | --- |
| `lit2mol/vllm.py` | `VLLMConfig`, `VLLMExtractor`, prompt building, structured output, response parsing |
| `lit2mol/extract.py` | CLI, file collection, concurrent batch orchestration |
| `lit2mol/__main__.py` | `python -m lit2mol` entry point |

## Start a vLLM server

On the GPU host serving the model:

```bash
vllm serve nvidia/Llama-3.1-8B-Instruct \
  --host 0.0.0.0 --port 8000 \
  --max-model-len 32768
```

Any OpenAI-compatible endpoint works; the model only needs to support the chat
completions API and guided decoding (all vLLM models do).

## Configure the client

Settings come from CLI flags or environment variables:

| Setting | Flag | Environment variable | Default |
| --- | --- | --- | --- |
| Base URL | `--base-url` | `VLLM_BASE_URL` | `http://localhost:8000/v1` |
| API key | `--api-key` | `VLLM_API_KEY` | `EMPTY` |
| Model | `--model` | `VLLM_MODEL` | none (required) |
| Structured mode | `--structured-mode` | `VLLM_STRUCTURED_MODE` | `guided_json` |
| Temperature | `--temperature` | | `0.0` |
| Top-p | `--top-p` | | `1.0` |
| Max tokens | `--max-tokens` | | `8192` |
| Max input chars | `--max-input-chars` | | `120000` |
| Request timeout | `--timeout` | | `600` |
| Seed | `--seed` | | unset |

```bash
export VLLM_BASE_URL=http://gpu-host:8000/v1
export VLLM_MODEL=nvidia/Llama-3.1-8B-Instruct
export VLLM_API_KEY=EMPTY
```

## Structured output

Two decoding modes are supported:

- `guided_json` (default) — sends the JSON Schema as vLLM's `guided_json`
  argument via `extra_body`; the server restricts tokens to the grammar. This
  works on all vLLM versions and needs no model-side JSON support.
- `response_format` — sends an OpenAI-style
  `response_format={"type": "json_schema", ...}` request.

Either way the response is parsed and validated with
`MolecularMetadata.model_validate`, so malformed or schema-violating output
raises `ExtractionError` instead of corrupting downstream data.

## Running extraction

Single file or directory:

```bash
.venv/bin/python -m lit2mol.extract refs/fulltext/PMC2672614.txt \
  --focus "phenylalanyl-tRNA synthetase (PheS/PheT)" \
  --out-dir outputs/phes \
  --base-url http://gpu-host:8000/v1 \
  --model nvidia/Llama-3.1-8B-Instruct
```

Batch over all retrieved full texts for a target complex (concurrent):

```bash
# PheS / PheRS
VLLM_MODEL=nvidia/Llama-3.1-8B-Instruct \
.venv/bin/python -m lit2mol.extract refs/fulltext \
  --focus "phenylalanyl-tRNA synthetase (PheS, PheT, PheRS)" \
  --out-dir outputs/phes --concurrency 8

# pyridine nucleotide transhydrogenase (PntAB / UdhA)
VLLM_MODEL=nvidia/Llama-3.1-8B-Instruct \
.venv/bin/python -m lit2mol.extract refs/fulltext \
  --focus "pyridine nucleotide transhydrogenase (PntA, PntB, PntAB)" \
  --out-dir outputs/pntab --concurrency 8
```

Useful flags: `--limit N` (process the first N files), `--pattern '*.txt'`
(glob used for directories), `--concurrency 1` (sequential), `--seed`.

Each input `PMCxxxx.txt` produces a validated `outputs/<id>.json`. The process
exits `0` when all files succeed, `1` when any file fails, and `2` when no input
files are found.

## Programmatic use

```python
from lit2mol import MolecularMetadata, SourceDocument, VLLMConfig, VLLMExtractor

config = VLLMConfig.from_env(base_url="http://gpu-host:8000/v1", model="nvidia/Llama-3.1-8B-Instruct")
extractor = VLLMExtractor(config)

text = open("refs/fulltext/PMC2672614.txt").read()
doc = extractor.extract(
    text,
    source=SourceDocument(pmcid="PMC2672614"),
    focus="phenylalanyl-tRNA synthetase (PheS/PheT)",
)
print(doc.model_dump_json(indent=2, exclude_none=True))
```

For several documents:

```python
from lit2mol.extract import run_batch
from pathlib import Path

results = run_batch(
    sorted(Path("refs/fulltext").glob("*.txt")),
    extractor,
    Path("outputs/phes"),
    focus="phenylalanyl-tRNA synthetase (PheS/PheT)",
    concurrency=8,
)
```

## Prompt and grounding

The system prompt instructs the model to populate the correct registries, use
document-unique ids and `*_ref` fields, attach `Evidence` (section + short
verbatim quote) to each claim, respect the controlled vocabularies, and emit
only JSON. The user message contains the focus, bibliographic source, the JSON
Schema, and the article text.

Long articles are clipped to `--max-input-chars` (default 120000) to fit the
server context window. Raise `--max-model-len` on the server and
`--max-input-chars` together if your full texts are longer; for very large
inputs, pre-chunk them and merge the resulting documents.

## Testing without a server

The test suite mocks the OpenAI client, so no GPU or network access is required:

```bash
.venv/bin/pytest -q tests/test_vllm.py tests/test_extract.py
```

See [testing.md](testing.md) for full reproduction steps and
[usage.md](usage.md) for using the schema models directly.
