"""Command-line entry point for screening full texts for protein complexes.

Example::

    export TYPESAFE_API_KEY=...
    python -m lit2mol.screen refs/fulltext --out-dir outputs/screen

Options may also come from a TOML file via ``--config`` (or ``./lit2mol.toml``),
using the ``[screen]`` and ``[typesafe]`` tables. Input is one or more PMC JATS
``.xml`` files (or ``.txt`` files, or directories containing them). For every
file a ``ComplexScreen`` document is written to ``<out-dir>/<id>.json``.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import sys
from pathlib import Path
from typing import Optional, Sequence

from lit2mol.config import build_run_config, discover_config, load_toml_config
from lit2mol.extract import BatchResult, collect_input_files, document_id, source_for
from lit2mol.typesafe import ComplexScreener, ScreenError, TypeSafeConfig, load_article

SCREEN_DEFAULTS = {"out_dir": "outputs/screen", "pattern": "*.xml", "concurrency": 4}


def run_screen(
    files: Sequence[Path],
    screener: ComplexScreener,
    out_dir: Path,
    focus: Optional[str] = None,
    concurrency: int = 4,
    limit: Optional[int] = None,
) -> list[BatchResult]:
    """Screen every file and write JSON results to ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    selected = list(files[:limit]) if limit else list(files)

    def process(path: Path) -> BatchResult:
        doc_id = document_id(path)
        try:
            result = screener.screen(load_article(path), source=source_for(path), focus=focus)
        except (ScreenError, OSError, ValueError) as exc:
            return BatchResult(id=doc_id, input_path=path, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - network/server errors
            return BatchResult(id=doc_id, input_path=path, error=f"{type(exc).__name__}: {exc}")
        output_path = out_dir / f"{doc_id}.json"
        output_path.write_text(result.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
        return BatchResult(id=doc_id, input_path=path, output_path=output_path)

    if concurrency <= 1 or len(selected) <= 1:
        return [process(path) for path in selected]

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(process, selected))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m lit2mol.screen",
        description="Screen full texts for protein complexes using TypeSafe.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Full-text .xml/.txt files or directories (may also come from [screen].paths).",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="TOML config file (defaults to ./lit2mol.toml when present).",
    )
    parser.add_argument("--focus", default=None, help="Complex to check for in addition to the generic screen.")
    parser.add_argument("--out-dir", default=None, help="Directory for JSON results.")
    parser.add_argument("--pattern", default=None, help="Glob used when a path is a directory.")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N files.")
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--api-key", default=None, help="TypeSafe API key (env TYPESAFE_API_KEY).")
    parser.add_argument("--model", default=None, help="TypeSafe model (env TYPESAFE_MODEL).")
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--max-chunk-chars", type=int, default=None)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config_path = discover_config(args.config)
        toml_data = load_toml_config(config_path) if config_path else {}
        run = build_run_config(
            {
                "paths": args.paths or None,
                "focus": args.focus,
                "out_dir": args.out_dir,
                "pattern": args.pattern,
                "limit": args.limit,
                "concurrency": args.concurrency,
            },
            toml_data.get("screen"),
            table="screen",
            defaults=SCREEN_DEFAULTS,
        )
        config = TypeSafeConfig.from_sources(
            cli={
                "api_key": args.api_key,
                "model": args.model,
                "timeout": args.timeout,
                "max_chunk_chars": args.max_chunk_chars,
            },
            toml=toml_data.get("typesafe"),
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    screener = ComplexScreener(config)

    files = collect_input_files(run.paths, pattern=run.pattern)
    if not files:
        print("no input files found", file=sys.stderr)
        return 2

    if config_path:
        print(f"Using config file {config_path}", file=sys.stderr)
    print(
        f"Screening {len(files)} file(s) with TypeSafe model {config.model!r} -> {run.out_dir}",
        file=sys.stderr,
    )
    results = run_screen(
        files,
        screener,
        Path(run.out_dir),
        focus=run.focus,
        concurrency=run.concurrency,
        limit=run.limit,
    )

    failures = [r for r in results if not r.ok]
    for result in results:
        if result.ok:
            print(f"[ok]   {result.id} -> {result.output_path}")
        else:
            print(f"[fail] {result.id}: {result.error}", file=sys.stderr)
    print(
        f"Done: {len(results) - len(failures)} succeeded, {len(failures)} failed.",
        file=sys.stderr,
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
