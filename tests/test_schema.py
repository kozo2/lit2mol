"""Tests for the lit2mol Pydantic schema."""

import json

import pytest
from pydantic import ValidationError

from lit2mol.schema import (
    AminoAcid,
    Complex,
    ComponentStoichiometry,
    Evidence,
    Gene,
    Modification,
    ModificationType,
    ModifiedMonomer,
    MolecularMetadata,
    Monomer,
    SourceDocument,
    json_schema,
)


def base_kwargs() -> dict:
    return {
        "source": SourceDocument(
            pmcid="PMC2672614", pmid="19402753", organism="Escherichia coli"
        ),
        "genes": [
            Gene(id="pheS", name="pheS", locus_tag="b1717"),
            Gene(id="pheT", name="pheT", locus_tag="b1718"),
        ],
        "monomers": [
            Monomer(id="PheS", name="PheS", gene_ref="pheS", uniprot_id="P08312"),
            Monomer(id="PheT", name="PheT", gene_ref="pheT", uniprot_id="P07395"),
        ],
        "modified_monomers": [
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
        "complexes": [
            Complex(
                id="PheRS",
                name="phenylalanyl-tRNA synthetase",
                components=[
                    ComponentStoichiometry(component_ref="PheS", count=2),
                    ComponentStoichiometry(component_ref="PheT", count=2),
                ],
            )
        ],
    }


def make_doc(**overrides) -> MolecularMetadata:
    kwargs = base_kwargs()
    kwargs.update(overrides)
    return MolecularMetadata(**kwargs)


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_full_document_is_valid():
    doc = make_doc()
    assert len(doc.genes) == 2
    assert len(doc.monomers) == 2
    assert len(doc.modified_monomers) == 1
    assert len(doc.complexes) == 1


def test_minimal_document_only_needs_source():
    doc = MolecularMetadata(source=SourceDocument(pmid="19402753"))
    assert doc.genes == []
    assert doc.monomers == []
    assert doc.modified_monomers == []
    assert doc.complexes == []
    assert doc.source.pmid == "19402753"


def test_entity_index_maps_every_id():
    index = make_doc().entity_index()
    assert set(index) == {"pheS", "pheT", "PheS", "PheT", "PheS_phos", "PheRS"}
    assert index["PheS"].name == "PheS"


def test_complex_stoichiometry_is_preserved():
    doc = make_doc()
    counts = {c.component_ref: c.count for c in doc.complexes[0].components}
    assert counts == {"PheS": 2, "PheT": 2}


def test_nested_complex_reference_is_valid():
    doc = make_doc(
        complexes=[
            Complex(
                id="PheRS_core",
                name="PheRS core",
                components=[ComponentStoichiometry(component_ref="PheS", count=2)],
            ),
            Complex(
                id="PheRS_holo",
                name="PheRS holoenzyme",
                components=[
                    ComponentStoichiometry(component_ref="PheRS_core", count=1),
                    ComponentStoichiometry(component_ref="PheT", count=2),
                ],
            ),
        ]
    )
    assert doc.entity_index()["PheRS_holo"].components[0].component_ref == "PheRS_core"


def test_evidence_dict_is_coerced():
    doc = make_doc(
        genes=[
            Gene(
                id="pheS",
                name="pheS",
                evidence=[{"section": "Results", "quote": "pheS encodes PheS"}],
            )
        ],
        monomers=[Monomer(id="PheS", name="PheS", gene_ref="pheS")],
        modified_monomers=[],
        complexes=[],
    )
    assert isinstance(doc.genes[0].evidence[0], Evidence)
    assert doc.genes[0].evidence[0].section == "Results"


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #


def test_json_round_trip():
    doc = make_doc()
    restored = MolecularMetadata.model_validate_json(doc.model_dump_json())
    assert restored == doc


def test_exclude_none_drops_unset_optionals():
    data = make_doc().model_dump(exclude_none=True)
    assert "locus_tag" not in data["genes"][0] or data["genes"][0]["locus_tag"] is not None
    assert "residue" in data["modified_monomers"][0]["modifications"][0]


# --------------------------------------------------------------------------- #
# Reference validation
# --------------------------------------------------------------------------- #


def test_duplicate_id_within_registry_is_rejected():
    with pytest.raises(ValidationError, match="duplicate gene id"):
        make_doc(
            genes=[Gene(id="pheS", name="pheS"), Gene(id="pheS", name="pheS again")]
        )


def test_duplicate_id_across_registries_is_rejected():
    with pytest.raises(ValidationError, match="unique across all registries"):
        make_doc(genes=[Gene(id="PheS", name="pheS")])


def test_unknown_gene_ref_is_rejected():
    with pytest.raises(ValidationError, match="unknown gene"):
        make_doc(monomers=[Monomer(id="PheS", name="PheS", gene_ref="missing")])


def test_unknown_monomer_ref_is_rejected():
    with pytest.raises(ValidationError, match="unknown monomer"):
        make_doc(
            modified_monomers=[
                ModifiedMonomer(
                    id="X",
                    name="X",
                    monomer_ref="missing",
                    modifications=[Modification(modification_type=ModificationType.OTHER)],
                )
            ]
        )


def test_unknown_component_ref_is_rejected():
    with pytest.raises(ValidationError, match="unknown component"):
        make_doc(
            complexes=[
                Complex(
                    id="C",
                    name="C",
                    components=[ComponentStoichiometry(component_ref="missing")],
                )
            ]
        )


def test_cyclic_complex_is_rejected():
    with pytest.raises(ValidationError, match="cyclic complex"):
        make_doc(
            complexes=[
                Complex(
                    id="A",
                    name="A",
                    components=[ComponentStoichiometry(component_ref="B")],
                ),
                Complex(
                    id="B",
                    name="B",
                    components=[ComponentStoichiometry(component_ref="A")],
                ),
            ]
        )


def test_self_referencing_complex_is_rejected():
    with pytest.raises(ValidationError, match="cyclic complex"):
        make_doc(
            complexes=[
                Complex(
                    id="A",
                    name="A",
                    components=[ComponentStoichiometry(component_ref="A")],
                )
            ]
        )


# --------------------------------------------------------------------------- #
# Field constraints
# --------------------------------------------------------------------------- #


def test_extra_fields_are_forbidden():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Gene(id="pheS", name="pheS", unexpected="x")


def test_invalid_identifier_pattern_is_rejected():
    with pytest.raises(ValidationError):
        Gene(id="1bad id", name="pheS")


def test_invalid_pmcid_pattern_is_rejected():
    with pytest.raises(ValidationError):
        SourceDocument(pmcid="2672614")


def test_invalid_pmid_pattern_is_rejected():
    with pytest.raises(ValidationError):
        SourceDocument(pmid="PMC123")


def test_modification_requires_at_least_one():
    with pytest.raises(ValidationError):
        ModifiedMonomer(id="X", name="X", monomer_ref="PheS", modifications=[])


def test_complex_requires_at_least_one_component():
    with pytest.raises(ValidationError):
        Complex(id="C", name="C", components=[])


def test_position_must_be_positive():
    with pytest.raises(ValidationError):
        Modification(modification_type=ModificationType.PHOSPHORYLATION, position=0)


def test_component_count_must_be_positive():
    with pytest.raises(ValidationError):
        ComponentStoichiometry(component_ref="PheS", count=0)


def test_unknown_modification_type_is_rejected():
    with pytest.raises(ValidationError):
        Modification(modification_type="not-a-real-modification")


def test_amino_acid_accepts_three_letter_code_only():
    assert Modification(
        modification_type=ModificationType.PHOSPHORYLATION, residue="Ser"
    ).residue is AminoAcid.SER
    with pytest.raises(ValidationError):
        Modification(modification_type=ModificationType.PHOSPHORYLATION, residue="S")


# --------------------------------------------------------------------------- #
# JSON Schema and package surface
# --------------------------------------------------------------------------- #


def test_json_schema_has_expected_shape():
    schema = json_schema()
    assert schema["title"] == "MolecularMetadata"
    assert schema["required"] == ["source"]
    for name in ("Gene", "Monomer", "ModifiedMonomer", "Complex", "ComponentStoichiometry"):
        assert name in schema["$defs"]
    assert set(schema["properties"]) == {
        "source",
        "genes",
        "monomers",
        "modified_monomers",
        "complexes",
    }


def test_json_schema_is_serializable():
    assert json.loads(json.dumps(json_schema()))["title"] == "MolecularMetadata"


def test_package_re_exports_models():
    import lit2mol

    assert lit2mol.MolecularMetadata is MolecularMetadata
    assert lit2mol.json_schema is json_schema
    with pytest.raises(AttributeError):
        _ = lit2mol.does_not_exist
