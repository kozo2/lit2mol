"""TOML configuration support for the extraction CLI.

Values may be supplied from three sources. Precedence, highest first:

1. command-line arguments
2. a TOML configuration file (``--config`` or ``./lit2mol.toml``)
3. environment variables / built-in defaults

The TOML file uses two tables::

    [vllm]
    base_url = "http://gpu-host:8000/v1"
    api_key = "EMPTY"
    model = "nvidia/Llama-3.1-8B-Instruct"

    [extraction]
    paths = ["refs/fulltext"]
    focus = "phenylalanyl-tRNA synthetase (PheS/PheT)"
    out_dir = "outputs/phes"
    concurrency = 8

The protein-complex screen (``python -m lit2mol.screen``) reads the same
run-level keys from a ``[screen]`` table and its connection settings from
``[typesafe]``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Optional

from pydantic import Field

from lit2mol.schema import StrictModel

DEFAULT_CONFIG_FILENAME = "lit2mol.toml"

RUN_DEFAULTS: dict[str, Any] = {
    "paths": [],
    "focus": None,
    "out_dir": "outputs",
    "pattern": "*.txt",
    "limit": None,
    "concurrency": 4,
}


class RunConfig(StrictModel):
    """Resolved run-level options for a batch extraction."""

    paths: list[str] = Field(default_factory=list)
    focus: Optional[str] = None
    out_dir: str = "outputs"
    pattern: str = "*.txt"
    limit: Optional[int] = Field(default=None, ge=1)
    concurrency: int = Field(default=4, ge=1)


def load_toml_config(path: Path) -> dict[str, Any]:
    """Parse a TOML configuration file."""
    with Path(path).open("rb") as fh:
        return tomllib.load(fh)


def discover_config(explicit: Optional[str]) -> Optional[Path]:
    """Return the config path to use, or ``None`` when there is no config.

    An explicit ``--config`` must exist; otherwise ``./lit2mol.toml`` is used
    when present.
    """
    if explicit:
        candidate = Path(explicit)
        if not candidate.is_file():
            raise FileNotFoundError(f"config file not found: {candidate}")
        return candidate.resolve()
    default = Path(DEFAULT_CONFIG_FILENAME)
    return default.resolve() if default.is_file() else None


def build_run_config(
    cli: dict[str, Any],
    toml_table: Optional[dict[str, Any]] = None,
    table: str = "extraction",
    defaults: Optional[dict[str, Any]] = None,
) -> RunConfig:
    """Merge CLI options, TOML values, and defaults into a :class:`RunConfig`.

    ``table`` names the TOML table in error messages; ``defaults`` overrides
    :data:`RUN_DEFAULTS` for commands with different defaults (e.g. screening).
    """
    toml_table = dict(toml_table or {})
    unknown = set(toml_table) - set(RunConfig.model_fields)
    if unknown:
        raise ValueError(f"unknown [{table}] keys: {sorted(unknown)}")

    merged: dict[str, Any] = {**RUN_DEFAULTS, **(defaults or {})}
    merged.update(toml_table)
    for key, value in cli.items():
        if value is not None:
            merged[key] = value
    return RunConfig(**merged)
