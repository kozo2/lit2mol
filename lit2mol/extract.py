"""Command-line entry point for extracting metadata with a remote vLLM server.

Example::

    python -m lit2mol.extract refs/fulltext \
        --focus "phenylalanyl-tRNA synthetase (PheS/PheT)" \
        --out-dir outputs/phes \
        --base-url http://gpu-host:8000/v1 \
        --model nvidia/Llama-3.1-8B-Instruct

Input is one or more ``.txt`` full-text files (or directories containing them).
For every file a validated ``MolecularMetadata`` document is written to
``<out-dir>/<id>.json``.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from lit2mol.schema import SourceDocument
from lit2mol.vllm import ExtractionError, VLLMConfig, VLLMExtractor

PMCID_RE = re.compile(r"^(PMC\d+)$", re.IGNORECASE)
DEFAULT_OUT_DIR = "outputs"
DEFAULT_CONCURRENCY = 4


@dataclass
class BatchResult:
    """Outcome of processing a single input file."""

    id: str
    input_path: Path
    output_path: Optional[Path] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def collect_input_files(paths: Sequence[str], pattern: str = "*.txt") -> list[Path]:
    """Expand directories and files into a de-duplicated, ordered file list."""
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files.extend(sorted(path.glob(pattern)))
        else:
            files.append(path)
    seen: set[Path] = set()
    unique: list[Path] = []
    for file in files:
        resolved = file.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(file)
    return unique


def document_id(path: Path) -> str:
    """Derive a stable id (usually the PMCID) from an input path."""
    return path.stem


def source_for(path: Path) -> SourceDocument:
    """Build a :class:`SourceDocument` for an input file."""
    stem = path.stem
    if PMCID_RE.match(stem):
        return SourceDocument(pmcid=stem.upper())
    return SourceDocument()


def run_batch(
    files: Sequence[Path],
    extractor: VLLMExtractor,
    out_dir: Path,
    focus: Optional[str] = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    limit: Optional[int] = None,
) -> list[BatchResult]:
    """Extract metadata for every file and write JSON results to ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    selected = list(files[:limit]) if limit else list(files)

    def process(path: Path) -> BatchResult:
        doc_id = document_id(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            doc = extractor.extract(text, source=source_for(path), focus=focus)
        except (ExtractionError, OSError) as exc:
            return BatchResult(id=doc_id, input_path=path, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - network/server errors
            return BatchResult(id=doc_id, input_path=path, error=f"{type(exc).__name__}: {exc}")
        output_path = out_dir / f"{doc_id}.json"
        output_path.write_text(doc.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
        return BatchResult(id=doc_id, input_path=path, output_path=output_path)

    if concurrency <= 1 or len(selected) <= 1:
        return [process(path) for path in selected]

    results: list[BatchResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(process, path): path for path in selected}
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    order = {path: i for i, path in enumerate(selected)}
    results.sort(key=lambda r: order[r.input_path])
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m lit2mol.extract",
        description="Extract molecular metadata from full texts using a remote vLLM server.",
    )
    parser.add_argument("paths", nargs="+", help="Full-text .txt files or directories.")
    parser.add_argument("--focus", default=None, help="Molecule/complex to focus the extraction on.")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="Directory for JSON results.")
    parser.add_argument("--pattern", default="*.txt", help="Glob used when a path is a directory.")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N files.")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--base-url", default=None, help="vLLM base URL (env VLLM_BASE_URL).")
    parser.add_argument("--api-key", default=None, help="API key (env VLLM_API_KEY).")
    parser.add_argument("--model", default=None, help="Model name (env VLLM_MODEL).")
    parser.add_argument(
        "--structured-mode",
        choices=["guided_json", "response_format"],
        default=None,
        help="How to constrain decoding (env VLLM_STRUCTURED_MODE).",
    )
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--top-p", type=float, default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--max-input-chars", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--seed", type=int, default=None)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    config = VLLMConfig.from_env(
        base_url=args.base_url,
        api_key=args.api_key,
        model=args.model,
        structured_mode=args.structured_mode,
        temperature=args.temperature,
        top_p=args.top_p,
        max_tokens=args.max_tokens,
        max_input_chars=args.max_input_chars,
        timeout=args.timeout,
        seed=args.seed,
    )
    extractor = VLLMExtractor(config)

    files = collect_input_files(args.paths, pattern=args.pattern)
    if not files:
        print("no input files found", file=sys.stderr)
        return 2

    print(
        f"Extracting {len(files)} file(s) with model {config.model!r} "
        f"at {config.base_url} -> {args.out_dir}",
        file=sys.stderr,
    )
    results = run_batch(
        files,
        extractor,
        Path(args.out_dir),
        focus=args.focus,
        concurrency=args.concurrency,
        limit=args.limit,
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
