# lit2mol
Molecular metadata extraction using NVIDIA Nemotron models

Metadata extraction is performed by an LLM served by a remote vLLM instance.
The CLI reads article full texts and writes validated JSON documents. Runs are
configured with a TOML file (command-line flags and environment variables
override it).

## Setup

Create a `uv`-managed virtual environment and install the dependencies:

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
```

## Run

```bash
cp lit2mol.toml.example lit2mol.toml   # edit base_url, model, focus, paths
.venv/bin/python -m lit2mol.extract --config lit2mol.toml
```

`lit2mol.toml`:

```toml
[vllm]
base_url = "http://gpu-host:8000/v1"
api_key = "EMPTY"
model = "nvidia/Llama-3.1-8B-Instruct"

[extraction]
paths = ["refs/fulltext"]
focus = "phenylalanyl-tRNA synthetase (PheS/PheT)"
out_dir = "outputs/phes"
concurrency = 8
```

To screen articles for protein complexes first (TypeSafe; needs
`TYPESAFE_API_KEY`):

```bash
.venv/bin/python -m lit2mol.screen refs/fulltext   # -> outputs/screen/<id>.json
```

Documentation:
- [docs/schema.md](docs/schema.md) — extraction target schema
  (gene → monomer → modified monomer, and complexes with stoichiometry)
- [docs/extraction.md](docs/extraction.md) — LLM extraction via a remote vLLM server
- [docs/screening.md](docs/screening.md) — protein-complex screening with TypeSafe
- [docs/usage.md](docs/usage.md) — using the Python/Pydantic scripts
- [docs/testing.md](docs/testing.md) — reproducing the test results
