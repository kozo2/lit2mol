# Reproducing the test results

The test suite validates the Pydantic models in `lit2mol/schema.py`, the remote
vLLM client in `lit2mol/vllm.py`, the TOML configuration layer in
`lit2mol/config.py`, the extraction CLI in `lit2mol/extract.py`, and the
TypeSafe protein-complex screen in `lit2mol/typesafe.py` / `lit2mol/screen.py`.
The network-facing clients are exercised with mocked OpenAI and TypeSafe
clients, so no GPU, vLLM server, or API key is required. This page lists the
exact steps and expected output needed to reproduce a green run from a clean
checkout.

## Recorded result

Run performed on a clean checkout at the repository root:

```
$ .venv/bin/pytest -q
........................................................................ [ 76%]
......................                                                   [100%]
94 passed in 0.30s
```

| Item | Value |
| --- | --- |
| Tests collected | 94 |
| Result | 94 passed, 0 failed, 0 skipped |
| Python | 3.12.14 |
| pytest | 9.1.1 |
| pydantic | 2.13.5 |
| pydantic-core | 2.46.5 |
| openai | 3.19.2 |
| typesafe-sdk | 0.7.1 |
| OS | macOS arm64 |

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (used to create the virtual environment).
  A standard `python -m venv` works too if your Python ships `ensurepip`.
- Network access on the first run so `uv` can download packages.

## Repro steps

```bash
# 1. clone and enter the repository
git clone https://github.com/kozo2/lit2mol.git
cd lit2mol

# 2. create the virtual environment
uv venv .venv --python 3.12

# 3. install runtime + dev dependencies
uv pip install --python .venv/bin/python -r requirements-dev.txt

# 4. run the suite
.venv/bin/pytest -q
```

Expected final line: `28 passed` (the number of tests may grow over time).

### One-liner

```bash
uv venv .venv --python 3.12 && \
uv pip install --python .venv/bin/python -r requirements-dev.txt && \
.venv/bin/pytest -q
```

## Installing the exact versions

`requirements.txt` / `requirements-dev.txt` use lower bounds. To match the
recorded run exactly, install this frozen set:

```bash
uv pip install --python .venv/bin/python \
  annotated-types==0.8.0 \
  anyio==4.15.1 \
  h11==0.16.0 \
  httpcore2==2.13.1 \
  httpx2==2.13.1 \
  idna==3.20 \
  iniconfig==2.3.0 \
  jiter==0.17.0 \
  openai==3.19.2 \
  packaging==26.3 \
  pluggy==1.6.0 \
  pydantic==2.13.5 \
  pydantic-core==2.46.5 \
  pygments==2.21.0 \
  pytest==9.1.1 \
  sniffio==1.3.1 \
  tenacity==9.1.4 \
  truststore==0.10.4 \
  typesafe-sdk==0.7.1 \
  typing-extensions==4.16.0 \
  typing-inspection==0.4.4
```

## Running subsets

```bash
.venv/bin/pytest -v                                   # show each test name
.venv/bin/pytest -q tests/test_schema.py             # schema models
.venv/bin/pytest -q tests/test_vllm.py               # vLLM client
.venv/bin/pytest -q tests/test_extract.py            # extraction CLI
.venv/bin/pytest -q tests/test_config.py             # TOML config layer
.venv/bin/pytest -q tests/test_screen.py             # TypeSafe screen
.venv/bin/pytest -q -k "complex"                     # only complex tests
.venv/bin/pytest -q -k "round_trip or json_schema"   # name-based selection
.venv/bin/pytest -q -x                               # stop at first failure
```

## What is verified

`tests/test_schema.py` groups assertions into:

- **Happy path** — full document, minimal document, `entity_index`,
  stoichiometry, nested complexes, evidence coercion.
- **Serialization** — `model_dump_json` round-trip, `exclude_none`.
- **Reference validation** — duplicate ids (within and across registries),
  unknown `gene_ref` / `monomer_ref` / `component_ref`, cyclic and
  self-referencing complexes.
- **Field constraints** — `extra="forbid"`, identifier/PMCID/PMID patterns,
  `min_length`, positive `position` and `count`, enum rejection.
- **Schema and package surface** — generated JSON Schema shape, JSON
  serializability, lazy re-exports.

`tests/test_vllm.py` covers prompt building (schema, focus, truncation),
response parsing (plain/fenced/invalid/schema-mismatch), `guided_json` and
`response_format` request construction, seed propagation, and `VLLMConfig`
loading from environment variables — all against a fake OpenAI client.

`tests/test_extract.py` covers directory expansion/deduplication, id and
`SourceDocument` derivation, concurrent `run_batch` output writing, ordering,
limits and error capture, and the CLI exit codes (0 success, 1 partial failure,
2 no inputs) with a stub extractor. It also drives `main` from TOML files,
including auto-discovery, CLI-over-TOML overrides, and invalid-key rejection.

`tests/test_config.py` covers TOML loading, explicit and default discovery, and
the `CLI > TOML > env > default` precedence for both `VLLMConfig` and
`RunConfig`.

`tests/test_screen.py` covers JATS XML and txt loading, paragraph chunking,
question construction (with and without a focus), max-over-chunks aggregation
and evidence selection, `TypeSafeConfig` precedence and API-key checks, custom
`[screen]` defaults, concurrent `run_screen` output and error capture, and the
screen CLI exit codes — all against a fake TypeSafe client.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `pytest: command not found` | Use the venv path: `.venv/bin/pytest`. |
| `ModuleNotFoundError: No module named 'lit2mol'` | Run pytest from the repository root; the root `conftest.py` adds it to `sys.path`. |
| `ModuleNotFoundError: No module named 'pydantic'` | Install dev deps: `uv pip install --python .venv/bin/python -r requirements-dev.txt`. |
| Version drift failures | Install the frozen set from the section above. |
| Stale `__pycache__` after edits | Remove with `find . -name __pycache__ -type d -exec rm -rf {} +`. |

The environment is throwaway: delete `.venv/` and repeat the repro steps at any
time (`.venv/`, `__pycache__/`, and `.pytest_cache/` are gitignored).
