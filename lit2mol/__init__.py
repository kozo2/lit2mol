"""lit2mol: molecular metadata extraction.

Public models are re-exported lazily from :mod:`lit2mol.schema` so that running
``python -m lit2mol.schema`` does not import the module twice.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AminoAcid",
    "Complex",
    "ComponentStoichiometry",
    "Entity",
    "Evidence",
    "Gene",
    "Modification",
    "ModificationType",
    "ModifiedMonomer",
    "MolecularMetadata",
    "Monomer",
    "SourceDocument",
    "json_schema",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from lit2mol import schema

        return getattr(schema, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
