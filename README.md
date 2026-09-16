# lit2mol
Molecular metadata extraction using NVIDIA Nemotron models

Metadata extraction is performed by an LLM served by a remote vLLM instance.
The CLI reads article full texts and writes validated JSON documents. Runs are
configured with a TOML file (command-line flags and environment variables
override it).

```bash
cp lit2mol.toml.example lit2mol.toml   # edit base_url, model, focus, paths
python -m lit2mol.extract --config lit2mol.toml
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

Documentation:
- [docs/schema.md](docs/schema.md) — extraction target schema
  (gene → monomer → modified monomer, and complexes with stoichiometry)
- [docs/extraction.md](docs/extraction.md) — LLM extraction via a remote vLLM server
- [docs/usage.md](docs/usage.md) — using the Python/Pydantic scripts
- [docs/testing.md](docs/testing.md) — reproducing the test results
