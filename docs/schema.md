# Molecular Metadata Schema

Strongly typed target schema for extracting molecular metadata from
literature full texts. It models the chain

```
Gene -> Monomer -> ModifiedMonomer
```

and recursive `Complex` definitions whose components may be monomers,
modified monomers, or other complexes, each with an explicit stoichiometry.

The schema is defined with [Pydantic v2](https://docs.pydantic.dev/) in
`lit2mol/schema.py`. Pydantic provides runtime validation, JSON
(de)serialization, and a generated JSON Schema that can be used directly as the
structured-output target for an LLM.

## Files

| Path | Purpose |
| --- | --- |
| `lit2mol/schema.py` | Model definitions and reference validation |
| `lit2mol/vllm.py` | Remote vLLM extraction client (see [extraction.md](extraction.md)) |
| `lit2mol/config.py` | TOML configuration and precedence (`RunConfig`, `build_run_config`) |
| `lit2mol/extract.py` | Extraction CLI and batch orchestration |
| `lit2mol/__init__.py` | Convenience re-exports of all public models |
| `schema.json` | Generated JSON Schema (`MolecularMetadata.model_json_schema()`) |
| `lit2mol.toml.example` | Example extraction configuration |
| `requirements.txt` | Runtime dependencies (`pydantic>=2.7`, `openai>=1.40`) |
| `tests/` | Pytest suite (see [usage.md](usage.md#11-running-the-tests)) |

## Entity graph

Entities live in flat registries and reference one another by a document-unique
`id`. This avoids duplicating definitions and keeps the structure easy for an
LLM to produce.

```
MolecularMetadata
├── source: SourceDocument            Bibliographic metadata (pmcid, pmid, doi, title, organism)
├── genes: [Gene]                     id, name, synonyms, organism, evidence
│                                     locus_tag, ncbi_gene_id
├── monomers: [Monomer]               id, name, synonyms, organism, evidence
│                                     gene_ref  -> Gene.id
│                                     uniprot_id
├── modified_monomers: [ModifiedMonomer]
│                                     id, name, synonyms, organism, evidence
│                                     monomer_ref -> Monomer.id
│                                     modifications: [Modification]
└── complexes: [Complex]              id, name, synonyms, organism, evidence
                                      components: [ComponentStoichiometry]
                                        component_ref -> Monomer | ModifiedMonomer | Complex
                                        count: positive integer
                                      description
```

## Model reference

### `SourceDocument`
Bibliographic metadata for the document an extraction came from.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `pmcid` | `str` | no | Pattern `^PMC\d+$` |
| `pmid` | `str` | no | Pattern `^\d+$` |
| `doi` | `str` | no | |
| `title` | `str` | no | |
| `organism` | `str` | no | e.g. `Escherichia coli` |

### `Entity` (base for `Gene`, `Monomer`, `ModifiedMonomer`, `Complex`)
| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | `str` | yes | Local unique identifier, pattern `^[A-Za-z_][A-Za-z0-9_.:-]*$` |
| `name` | `str` | yes | Primary name, non-empty |
| `synonyms` | `list[str]` | no | Defaults to `[]` |
| `organism` | `str` | no | |
| `evidence` | `list[Evidence]` | no | Defaults to `[]` |

### `Gene`
Adds:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `locus_tag` | `str` | no | e.g. `b3372` |
| `ncbi_gene_id` | `int` | no | |

### `Monomer`
A single polypeptide chain (gene product). Adds:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `gene_ref` | `str` | no | `id` of the encoding `Gene` |
| `uniprot_id` | `str` | no | |

### `ModifiedMonomer`
A monomer carrying one or more modifications. Adds:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `monomer_ref` | `str` | yes | `id` of the unmodified `Monomer` |
| `modifications` | `list[Modification]` | yes | At least one |

### `Modification`
| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `modification_type` | `ModificationType` | yes | Controlled vocabulary (see below) |
| `residue` | `AminoAcid` | no | Three-letter code, e.g. `Ser` |
| `position` | `int` | no | 1-based sequence position |
| `description` | `str` | no | For N-/C-terminal or otherwise un-numbered sites |
| `evidence` | `list[Evidence]` | no | |

### `ComponentStoichiometry`
| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `component_ref` | `str` | yes | `id` of a `Monomer`, `ModifiedMonomer`, or nested `Complex` |
| `count` | `int` | no | Positive; number of copies, defaults to `1` |
| `evidence` | `list[Evidence]` | no | |

### `Complex`
A molecular assembly. Adds:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `components` | `list[ComponentStoichiometry]` | yes | At least one |
| `description` | `str` | no | |

### `Evidence`
| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `pmcid` | `str` | no | Pattern `^PMC\d+$` |
| `pmid` | `str` | no | Pattern `^\d+$` |
| `section` | `str` | no | Section or figure/table label |
| `quote` | `str` | no | Supporting snippet from the source |

### `MolecularMetadata`
Root object. All collections default to `[]` except `source`, which is required.

| Field | Type | Required |
| --- | --- | --- |
| `source` | `SourceDocument` | yes |
| `genes` | `list[Gene]` | no |
| `monomers` | `list[Monomer]` | no |
| `modified_monomers` | `list[ModifiedMonomer]` | no |
| `complexes` | `list[Complex]` | no |

## Controlled vocabularies

`ModificationType`: `phosphorylation`, `acetylation`, `methylation`,
`adenylylation`, `uridylylation`, `glycosylation`, `hydroxylation`, `oxidation`,
`nitrosylation`, `sumoylation`, `ubiquitination`, `palmitoylation`,
`myristoylation`, `prenylation`, `carboxylation`, `proteolytic_cleavage`,
`disulfide_bond`, `lactylation`, `succinylation`, `unknown`, `other`.

`AminoAcid`: `Ala`, `Arg`, `Asn`, `Asp`, `Cys`, `Gln`, `Glu`, `Gly`, `His`,
`Ile`, `Leu`, `Lys`, `Met`, `Phe`, `Pro`, `Ser`, `Thr`, `Trp`, `Tyr`, `Val`,
`Sec`, `Pyl`.

Use `unknown`/`other` combined with `Modification.description` when a
modification does not fit the vocabulary.

## Validation rules

`MolecularMetadata` runs a post-validation pass and raises `ValidationError`
when any of the following fail:

1. `id`s are unique within each registry.
2. `id`s are unique across all registries (so a `component_ref` is unambiguous).
3. Every `Monomer.gene_ref` resolves to an existing `Gene`.
4. Every `ModifiedMonomer.monomer_ref` resolves to an existing `Monomer`.
5. Every `Complex.components[].component_ref` resolves to an existing
   `Monomer`, `ModifiedMonomer`, or `Complex`.
6. Complex component graph contains no cycles.

All models set `extra="forbid"`, so unexpected fields are rejected.

## Usage

### Construct and validate

```python
from lit2mol.schema import (
    AminoAcid, Complex, ComponentStoichiometry, Gene, Modification,
    ModificationType, ModifiedMonomer, MolecularMetadata, Monomer, SourceDocument,
)

doc = MolecularMetadata(
    source=SourceDocument(pmcid="PMC2672614", pmid="19402753", organism="Escherichia coli"),
    genes=[Gene(id="pheS", name="pheS", locus_tag="b1717")],
    monomers=[Monomer(id="PheS", name="PheS", gene_ref="pheS", uniprot_id="P08312")],
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
                ComponentStoichiometry(component_ref="PheS_phos", count=1),
            ],
        )
    ],
)

print(doc.entity_index())  # {'pheS': ..., 'PheS': ..., 'PheS_phos': ..., 'PheRS': ...}
```

### Load LLM output from JSON

```python
doc = MolecularMetadata.model_validate_json(raw_json)
```

### Produce the JSON Schema for structured output

```bash
.venv/bin/python -m lit2mol.schema > schema.json
```

or in code:

```python
from lit2mol.schema import json_schema
schema = json_schema()
```

## Development setup

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
```

Run anything with the project on the path via `.venv/bin/python` from the
repository root.
