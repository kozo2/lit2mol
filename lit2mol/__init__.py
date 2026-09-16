"""lit2mol: molecular metadata extraction using a remote vLLM server.

Public names are re-exported lazily so that running ``python -m lit2mol`` or
``python -m lit2mol.schema`` does not import modules twice.
"""

from __future__ import annotations

from typing import Any

_EXPORTS = {
    "lit2mol.schema": [
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
    ],
    "lit2mol.vllm": [
        "ExtractionError",
        "VLLMConfig",
        "VLLMExtractor",
        "build_messages",
        "parse_response",
    ],
    "lit2mol.extract": [
        "BatchResult",
        "collect_input_files",
        "document_id",
        "main",
        "run_batch",
        "source_for",
    ],
}

__all__ = sorted(name for names in _EXPORTS.values() for name in names)

_LOOKUP = {name: module for module, names in _EXPORTS.items() for name in names}


def __getattr__(name: str) -> Any:
    module_name = _LOOKUP.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module_name), name)


def __dir__() -> list[str]:
    return sorted(__all__)
