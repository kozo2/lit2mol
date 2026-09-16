# lit2mol
Molecular metadata extraction using NVIDIA Nemotron models

Metadata extraction is performed by an LLM served by a remote vLLM instance.
The CLI reads article full texts and writes validated JSON documents.

```bash
VLLM_MODEL=nvidia/Llama-3.1-8B-Instruct \
python -m lit2mol.extract refs/fulltext \
  --focus "phenylalanyl-tRNA synthetase (PheS/PheT)" \
  --out-dir outputs/phes \
  --base-url http://gpu-host:8000/v1
```

Documentation:
- [docs/schema.md](docs/schema.md) — extraction target schema
  (gene → monomer → modified monomer, and complexes with stoichiometry)
- [docs/extraction.md](docs/extraction.md) — LLM extraction via a remote vLLM server
- [docs/usage.md](docs/usage.md) — using the Python/Pydantic scripts
- [docs/testing.md](docs/testing.md) — reproducing the test results
