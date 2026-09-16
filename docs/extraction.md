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
| `lit2mol/config.py` | TOML loading and CLI/file/env precedence (`RunConfig`, `build_run_config`) |
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

## Configuration file (recommended)

Runs are configured with a TOML file. Start from the template
`lit2mol.toml.example`:

```toml
[vllm]
base_url = "http://gpu-host:8000/v1"
api_key = "EMPTY"
model = "nvidia/Llama-3.1-8B-Instruct"
structured_mode = "guided_json"
temperature = 0.0
max_tokens = 8192

[extraction]
paths = ["refs/fulltext"]
focus = "phenylalanyl-tRNA synthetase (PheS/PheT)"
out_dir = "outputs/phes"
concurrency = 8
```

Copy it into place and run. The CLI auto-discovers `./lit2mol.toml`, and paths
may be supplied by the file so no positional arguments are needed:

```bash
cp lit2mol.toml.example lit2mol.toml
python -m lit2mol.extract            # auto-discovers ./lit2mol.toml
python -m lit2mol.extract --config path/to/other.toml
```

Keep separate files per target complex and switch between them:

```toml
# lit2mol.pntab.toml
[extraction]
paths = ["refs/fulltext"]
focus = "pyridine nucleotide transhydrogenase (PntA, PntB, PntAB)"
out_dir = "outputs/pntab"
concurrency = 8
```

```bash
python -m lit2mol.extract --config lit2mol.phes.toml
python -m lit2mol.extract --config lit2mol.pntab.toml
```

Any explicit flag still wins over the file, so you can keep a project file and
override one value:

```bash
python -m lit2mol.extract --config lit2mol.toml --model other-model --limit 5
```

Unknown keys under `[vllm]` or `[extraction]` are rejected with a configuration
error (exit code `2`) rather than being silently ignored.

## Configuration reference

Settings come from command-line flags, a TOML file, or environment variables.
Precedence, highest first:

1. command-line arguments
2. TOML file (`--config FILE`, or `./lit2mol.toml` when present)
3. environment variables
4. built-in defaults

`[vllm]` settings:

| Setting | Flag | TOML `[vllm]` key | Environment variable | Default |
| --- | --- | --- | --- | --- |
| Base URL | `--base-url` | `base_url` | `VLLM_BASE_URL` | `http://localhost:8000/v1` |
| API key | `--api-key` | `api_key` | `VLLM_API_KEY` | `EMPTY` |
| Model | `--model` | `model` | `VLLM_MODEL` | none (required) |
| Structured mode | `--structured-mode` | `structured_mode` | `VLLM_STRUCTURED_MODE` | `guided_json` |
| Temperature | `--temperature` | `temperature` | | `0.0` |
| Top-p | `--top-p` | `top_p` | | `1.0` |
| Max tokens | `--max-tokens` | `max_tokens` | | `8192` |
| Max input chars | `--max-input-chars` | `max_input_chars` | | `120000` |
| Request timeout | `--timeout` | `timeout` | | `600` |
| Seed | `--seed` | `seed` | | unset |

`[extraction]` settings:

| Setting | Flag | TOML `[extraction]` key | Default |
| --- | --- | --- | --- |
| Input files/dirs | positional `paths` | `paths` (array) | none |
| Focus | `--focus` | `focus` | all molecules |
| Output directory | `--out-dir` | `out_dir` | `outputs` |
| Directory glob | `--pattern` | `pattern` | `*.txt` |
| Limit | `--limit` | `limit` | none |
| Concurrency | `--concurrency` | `concurrency` | `4` |

Environment variables are a fallback when neither a flag nor the TOML file sets
a value:

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

Preferred: describe the run in a TOML file and invoke the CLI.

```toml
# lit2mol.phes.toml
[vllm]
base_url = "http://gpu-host:8000/v1"
api_key = "EMPTY"
model = "nvidia/Llama-3.1-8B-Instruct"

[extraction]
paths = ["refs/fulltext"]
focus = "phenylalanyl-tRNA synthetase (PheS, PheT, PheRS)"
out_dir = "outputs/phes"
concurrency = 8
```

```bash
.venv/bin/python -m lit2mol.extract --config lit2mol.phes.toml
```

For a second target, use a separate complete file:

```toml
# lit2mol.pntab.toml
[vllm]
base_url = "http://gpu-host:8000/v1"
api_key = "EMPTY"
model = "nvidia/Llama-3.1-8B-Instruct"

[extraction]
paths = ["refs/fulltext"]
focus = "pyridine nucleotide transhydrogenase (PntA, PntB, PntAB)"
out_dir = "outputs/pntab"
concurrency = 8
```

```bash
.venv/bin/python -m lit2mol.extract --config lit2mol.pntab.toml
```

Flags can still be used for one-off runs without a file, and override any TOML
value:

```bash
# ad hoc single file
.venv/bin/python -m lit2mol.extract refs/fulltext/PMC2672614.txt \
  --focus "phenylalanyl-tRNA synthetase (PheS/PheT)" \
  --out-dir outputs/phes \
  --base-url http://gpu-host:8000/v1 \
  --model nvidia/Llama-3.1-8B-Instruct

# same run as lit2mol.phes.toml, overriding the model for this invocation
.venv/bin/python -m lit2mol.extract --config lit2mol.phes.toml --model other-model
```

Useful flags: `--limit N` (process the first N files), `--pattern '*.txt'`
(glob used for directories), `--concurrency 1` (sequential), `--seed`.

Each input `PMCxxxx.txt` produces a validated `outputs/<id>.json`. The process
exits `0` when all files succeed, `1` when any file fails, and `2` when no input
files are found.

## Programmatic use

Build the client from the same TOML file the CLI uses:

```python
from lit2mol.config import load_toml_config
from lit2mol.schema import SourceDocument
from lit2mol.vllm import VLLMConfig, VLLMExtractor

toml_data = load_toml_config("lit2mol.toml")
config = VLLMConfig.from_sources(toml=toml_data.get("vllm"))
extractor = VLLMExtractor(config)

text = open("refs/fulltext/PMC2672614.txt").read()
doc = extractor.extract(
    text,
    source=SourceDocument(pmcid="PMC2672614"),
    focus="phenylalanyl-tRNA synthetase (PheS/PheT)",
)
print(doc.model_dump_json(indent=2, exclude_none=True))
```

Without a TOML file, pass values directly (CLI-style keywords to `from_env`):

```python
config = VLLMConfig.from_env(base_url="http://gpu-host:8000/v1", model="nvidia/Llama-3.1-8B-Instruct")
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

Configuration can also be assembled from the same sources as the CLI:

```python
from pathlib import Path

from lit2mol.config import build_run_config, load_toml_config
from lit2mol.extract import collect_input_files, run_batch
from lit2mol.vllm import VLLMConfig, VLLMExtractor

toml_data = load_toml_config("lit2mol.toml")
run = build_run_config({}, toml_data.get("extraction"))
config = VLLMConfig.from_sources(toml=toml_data.get("vllm"))

results = run_batch(
    collect_input_files(run.paths, pattern=run.pattern),
    VLLMExtractor(config),
    Path(run.out_dir),
    focus=run.focus,
    concurrency=run.concurrency,
    limit=run.limit,
)
```

## Prompt and grounding

The system prompt instructs the model to populate the correct registries, use
document-unique ids and `*_ref` fields, attach `Evidence` (section + short
verbatim quote) to each claim, respect the controlled vocabularies, and emit
only JSON. The user message contains the focus, bibliographic source, the JSON
Schema, and the article text.

Long articles are clipped to `max_input_chars` (`--max-input-chars`, TOML
`[vllm].max_input_chars`, default 120000) to fit the server context window.
Raise `--max-model-len` on the server and `max_input_chars` together if your
full texts are longer; for very large inputs, pre-chunk them and merge the
resulting documents.

## Testing without a server

The test suite mocks the OpenAI client, so no GPU or network access is required:

```bash
.venv/bin/pytest -q tests/test_vllm.py tests/test_extract.py tests/test_config.py
```

See [testing.md](testing.md) for full reproduction steps and
[usage.md](usage.md) for using the schema models directly.
