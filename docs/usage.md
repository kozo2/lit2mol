# Using the Python / Pydantic scripts

Practical guide to the `lit2mol` schema package. The models live in
`lit2mol/schema.py` and are built with [Pydantic v2](https://docs.pydantic.dev/).
See [schema.md](schema.md) for the full field reference; this guide focuses on
how to run and use the code.

## 1. Environment setup

The project uses a `uv`-managed virtual environment (committed
`requirements.txt` pins `pydantic>=2.7`).

```bash
# from the repository root
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
```

Run Python through the venv interpreter so `lit2mol` is importable from the
repository root:

```bash
.venv/bin/python -c "import lit2mol; print(lit2mol.__all__)"
```

If you prefer an activated shell:

```bash
source .venv/bin/activate
python -c "import lit2mol; print(lit2mol.__all__)"
```

## 2. Importing the models

Both import styles are supported:

```python
# lazy re-exports from the package
from lit2mol import Gene, Monomer, MolecularMetadata, SourceDocument

# or import directly from the module
from lit2mol.schema import MolecularMetadata
```

`from lit2mol import ...` resolves lazily via `lit2mol/__init__.py`, so it does
not pull in the schema until an attribute is actually used.

## 3. Building a document

Construct models with plain Python objects. Pydantic validates and coerces as
you go.

```python
from lit2mol.schema import (
    AminoAcid,
    Complex,
    ComponentStoichiometry,
    Gene,
    Modification,
    ModificationType,
    ModifiedMonomer,
    MolecularMetadata,
    Monomer,
    SourceDocument,
)

doc = MolecularMetadata(
    source=SourceDocument(
        pmcid="PMC2672614",
        pmid="19402753",
        organism="Escherichia coli",
    ),
    genes=[
        Gene(id="pheS", name="pheS", locus_tag="b1717"),
        Gene(id="pheT", name="pheT", locus_tag="b1718"),
    ],
    monomers=[
        Monomer(id="PheS", name="PheS", gene_ref="pheS", uniprot_id="P08312"),
        Monomer(id="PheT", name="PheT", gene_ref="pheT", uniprot_id="P07395"),
    ],
    modified_monomers=[
        ModifiedMonomer(
            id="PheS_phos",
            name="phosphorylated PheS",
            monomer_ref="PheS",
            modifications=[
                Modification(
                    modification_type=ModificationType.PHOSPHORYLATION,
                    residue=AminoAcid.SER,
                    position=91,
                    evidence=[{"section": "Results", "quote": "PheS is phosphorylated at Ser91"}],
                )
            ],
        )
    ],
    complexes=[
        Complex(
            id="PheRS",
            name="phenylalanyl-tRNA synthetase",
            components=[
                ComponentStoichiometry(component_ref="PheS", count=2),
                ComponentStoichiometry(component_ref="PheT", count=2),
            ],
        )
    ],
)
```

Nested input is accepted too: `evidence=[{"section": "Results"}]` is coerced
into an `Evidence` instance automatically.

## 4. Serializing

```python
doc.model_dump()                          # nested dict
doc.model_dump(exclude_none=True)         # drop unset optional fields
doc.model_dump_json(indent=2)             # compact/pretty JSON string
doc.model_dump_json(exclude_none=True)
```

Write/read JSON files:

```python
from pathlib import Path

Path("out.json").write_text(doc.model_dump_json(indent=2, exclude_none=True))
doc2 = MolecularMetadata.model_validate_json(Path("out.json").read_text())
```

## 5. Validating LLM output

This is the primary use case: parse a model/LLM JSON response into a validated
document.

```python
from pydantic import ValidationError
from lit2mol.schema import MolecularMetadata

raw = '{"source": {"pmcid": "PMC2672614"}, "genes": [], "monomers": [], "complexes": []}'
try:
    doc = MolecularMetadata.model_validate_json(raw)
except ValidationError as exc:
    print(exc)
    for err in exc.errors():
        print(err["loc"], err["msg"])
```

You can also validate an already-parsed dict with
`MolecularMetadata.model_validate(data)`.

## 6. Generating the JSON Schema

The JSON Schema is the structured-output target to hand to an LLM.

```bash
# write the schema to a file
.venv/bin/python -m lit2mol.schema > schema.json
```

Or from code:

```python
from lit2mol import json_schema

schema = json_schema()
```

Feeding it to an OpenAI-compatible endpoint (e.g. NVIDIA Nemotron):

```python
response_format = {
    "type": "json_schema",
    "json_schema": {"name": "MolecularMetadata", "schema": json_schema()},
}
```

## 7. Traversing the result

```python
index = doc.entity_index()          # {id: entity} across all registries
index["PheS"].name                  # 'PheS'

# walk a complex and resolve each component
for comp in doc.complexes[0].components:
    target = index[comp.component_ref]
    print(comp.count, target.name)
```

A small helper to compute the subunit formula of a flat complex:

```python
from collections import Counter

def formula(complex_id, index):
    c = index[complex_id]
    return Counter({p.component_ref: p.count for p in c.components})
```

## 8. Partial extractions

All collections except `source` default to empty, so you can emit only what a
paper supports:

```python
MolecularMetadata(source=SourceDocument(pmid="19402753"))            # metadata only
MolecularMetadata(source=SourceDocument(), genes=[...])               # genes only
```

`ModifiedMonomer.modifications` requires at least one entry, and
`Complex.components` requires at least one entry.

## 9. Validation errors you may hit

| Error | Fix |
| --- | --- |
| `duplicate <kind> id` | Make `id`s unique within a registry |
| `entity ids must be unique across all registries` | Component refs must be unambiguous; rename colliding ids |
| `monomer 'X' references unknown gene 'Y'` | Add the missing `Gene` or correct `gene_ref` |
| `modified monomer 'X' references unknown monomer 'Y'` | Add the missing `Monomer` or correct `monomer_ref` |
| `complex 'X' references unknown component 'Y'` | Add the missing monomer/modified monomer/complex |
| `cyclic complex definition detected` | Break the component reference cycle |
| `Extra inputs are not permitted` | Remove unexpected fields; models use `extra="forbid"` |

## 10. Running a quick check

```bash
.venv/bin/python - <<'PY'
from lit2mol.schema import MolecularMetadata, SourceDocument
doc = MolecularMetadata(source=SourceDocument(pmcid="PMC2672614"))
print(doc.model_dump_json(exclude_none=True))
PY
```

## 11. Running the tests

Install the dev dependencies and run pytest from the repository root:

```bash
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/pytest -q
```

The suite covers the schema models (`tests/test_schema.py`), the remote vLLM
client (`tests/test_vllm.py`, mocked so no server is needed), and the extraction
CLI (`tests/test_extract.py`). A root `conftest.py` puts the repository root on
`sys.path` so `lit2mol` is importable without installing the package.

See [testing.md](testing.md) for the recorded result, frozen dependency versions,
and step-by-step reproduction instructions.
