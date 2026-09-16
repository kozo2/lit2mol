"""Strongly typed target schema for molecular metadata extraction.

The schema models the chain

    Gene -> Monomer -> ModifiedMonomer

and recursive ``Complex`` definitions whose components are monomers, modified
monomers, and other complexes, each with an explicit stoichiometry.

Entities are stored in flat registries and reference one another by ``id``.
This keeps definitions non-redundant and makes the model easy to emit with an
LLM via the generated JSON Schema.
"""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

IDENTIFIER_PATTERN = r"^[A-Za-z_][A-Za-z0-9_.:-]*$"

Identifier = Annotated[str, Field(pattern=IDENTIFIER_PATTERN)]


class StrictModel(BaseModel):
    """Base model that rejects unknown fields."""

    model_config = ConfigDict(extra="forbid")


class ModificationType(str, Enum):
    """Controlled vocabulary of post-translational modifications."""

    PHOSPHORYLATION = "phosphorylation"
    ACETYLATION = "acetylation"
    METHYLATION = "methylation"
    ADENYLYLATION = "adenylylation"
    URIDYLYLATION = "uridylylation"
    GLYCOSYLATION = "glycosylation"
    HYDROXYLATION = "hydroxylation"
    OXIDATION = "oxidation"
    NITROSYLATION = "nitrosylation"
    SUMOYLATION = "sumoylation"
    UBIQUITINATION = "ubiquitination"
    PALMITOYLATION = "palmitoylation"
    MYRISTOYLATION = "myristoylation"
    PRENYLATION = "prenylation"
    CARBOXYLATION = "carboxylation"
    PROTEOLYTIC_CLEAVAGE = "proteolytic_cleavage"
    DISULFIDE_BOND = "disulfide_bond"
    LACTYLATION = "lactylation"
    SUCCINYLATION = "succinylation"
    UNKNOWN = "unknown"
    OTHER = "other"


class AminoAcid(str, Enum):
    """Three-letter amino-acid codes."""

    ALA = "Ala"
    ARG = "Arg"
    ASN = "Asn"
    ASP = "Asp"
    CYS = "Cys"
    GLN = "Gln"
    GLU = "Glu"
    GLY = "Gly"
    HIS = "His"
    ILE = "Ile"
    LEU = "Leu"
    LYS = "Lys"
    MET = "Met"
    PHE = "Phe"
    PRO = "Pro"
    SER = "Ser"
    THR = "Thr"
    TRP = "Trp"
    TYR = "Tyr"
    VAL = "Val"
    SEC = "Sec"
    PYL = "Pyl"


class Evidence(StrictModel):
    """Provenance for a single extracted statement."""

    pmcid: Optional[str] = Field(default=None, pattern=r"^PMC\d+$")
    pmid: Optional[str] = Field(default=None, pattern=r"^\d+$")
    section: Optional[str] = Field(default=None, description="Section or figure/table label.")
    quote: Optional[str] = Field(default=None, description="Supporting snippet from the source.")


class SourceDocument(StrictModel):
    """Bibliographic metadata of the document the entities were extracted from."""

    pmcid: Optional[str] = Field(default=None, pattern=r"^PMC\d+$")
    pmid: Optional[str] = Field(default=None, pattern=r"^\d+$")
    doi: Optional[str] = None
    title: Optional[str] = None
    organism: Optional[str] = Field(default=None, description="e.g. 'Escherichia coli'.")


class Entity(StrictModel):
    """Shared fields for every molecular entity."""

    id: Identifier = Field(description="Local, document-unique identifier used for references.")
    name: str = Field(min_length=1, description="Primary name of the entity.")
    synonyms: list[str] = Field(default_factory=list)
    organism: Optional[str] = None
    evidence: list[Evidence] = Field(default_factory=list)


class Gene(Entity):
    """A gene that encodes a monomer."""

    locus_tag: Optional[str] = Field(default=None, description="e.g. 'b3372'.")
    ncbi_gene_id: Optional[int] = None


class Modification(StrictModel):
    """A chemical modification of a monomer."""

    modification_type: ModificationType
    residue: Optional[AminoAcid] = Field(default=None, description="Residue bearing the modification.")
    position: Optional[int] = Field(default=None, ge=1, description="Sequence position of the residue.")
    description: Optional[str] = Field(
        default=None, description="Use for N-/C-terminal or otherwise un-numbered sites."
    )
    evidence: list[Evidence] = Field(default_factory=list)


class Monomer(Entity):
    """A single polypeptide chain (gene product)."""

    gene_ref: Optional[Identifier] = Field(default=None, description="id of the encoding Gene.")
    uniprot_id: Optional[str] = None


class ModifiedMonomer(Entity):
    """A monomer carrying one or more modifications."""

    monomer_ref: Identifier = Field(description="id of the unmodified Monomer.")
    modifications: list[Modification] = Field(min_length=1)


class ComponentStoichiometry(StrictModel):
    """A component of a complex together with its copy number."""

    component_ref: Identifier = Field(
        description="id of a Monomer, ModifiedMonomer, or nested Complex."
    )
    count: PositiveInt = Field(default=1, description="Number of copies in the complex.")
    evidence: list[Evidence] = Field(default_factory=list)


class Complex(Entity):
    """A molecular assembly with defined stoichiometry."""

    components: list[ComponentStoichiometry] = Field(min_length=1)
    description: Optional[str] = None


class MolecularMetadata(StrictModel):
    """Root extraction result: flat entity registries referencing each other by id."""

    source: SourceDocument
    genes: list[Gene] = Field(default_factory=list)
    monomers: list[Monomer] = Field(default_factory=list)
    modified_monomers: list[ModifiedMonomer] = Field(default_factory=list)
    complexes: list[Complex] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_references(self) -> "MolecularMetadata":
        gene_ids = {g.id for g in self.genes}
        monomer_ids = {m.id for m in self.monomers}
        modified_ids = {mm.id for mm in self.modified_monomers}
        complex_ids = {c.id for c in self.complexes}

        for label, ids, collection in (
            ("gene", gene_ids, self.genes),
            ("monomer", monomer_ids, self.monomers),
            ("modified_monomer", modified_ids, self.modified_monomers),
            ("complex", complex_ids, self.complexes),
        ):
            if len(ids) != len(collection):
                raise ValueError(f"duplicate {label} id")

        all_ids = gene_ids | monomer_ids | modified_ids | complex_ids
        if len(all_ids) != sum(len(s) for s in (gene_ids, monomer_ids, modified_ids, complex_ids)):
            raise ValueError("entity ids must be unique across all registries")

        for monomer in self.monomers:
            if monomer.gene_ref is not None and monomer.gene_ref not in gene_ids:
                raise ValueError(f"monomer {monomer.id!r} references unknown gene {monomer.gene_ref!r}")

        for mm in self.modified_monomers:
            if mm.monomer_ref not in monomer_ids:
                raise ValueError(
                    f"modified monomer {mm.id!r} references unknown monomer {mm.monomer_ref!r}"
                )

        component_targets = monomer_ids | modified_ids | complex_ids
        for complex_ in self.complexes:
            for comp in complex_.components:
                if comp.component_ref not in component_targets:
                    raise ValueError(
                        f"complex {complex_.id!r} references unknown component {comp.component_ref!r}"
                    )

        self._check_complex_cycles()
        return self

    def _check_complex_cycles(self) -> None:
        by_id = {c.id: c for c in self.complexes}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visited:
                return
            if node in visiting:
                raise ValueError(f"cyclic complex definition detected at {node!r}")
            visiting.add(node)
            for comp in by_id[node].components:
                if comp.component_ref in by_id:
                    visit(comp.component_ref)
            visiting.discard(node)
            visited.add(node)

        for node in by_id:
            visit(node)

    def entity_index(self) -> dict[str, Entity]:
        """Return a mapping of every entity id to its model instance."""
        index: dict[str, Entity] = {}
        for collection in (self.genes, self.monomers, self.modified_monomers, self.complexes):
            for entity in collection:
                index[entity.id] = entity
        return index


def json_schema() -> dict:
    """Return the JSON Schema for the extraction target."""
    return MolecularMetadata.model_json_schema()


def main() -> None:
    print(json.dumps(json_schema(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
