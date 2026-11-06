"""Command line entry point: `docextract extract | eval | generate`."""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import __version__, baseline
from .data import HOLDOUT, generate
from .evaluate import Report, load_truth
from .validate import check

HERE = Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="docextract", description="Extract validated JSON from invoices.")
    p.add_argument("--version", action="version", version=f"docextract {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    ex = sub.add_parser("extract", help="extract one document and validate it")
    ex.add_argument("file")
    ex.add_argument("--offline", action="store_true", help="use the regex baseline instead of Claude")
    ex.add_argument("--model", default="claude-opus-5-5")
    ex.add_argument("--effort", default="low", choices=("low", "medium", "high", "xhigh", "max"))

    ev = sub.add_parser("eval", help="score extraction against a folder's truth.jsonl")
    ev.add_argument("folder", help="a folder with invoices/ and truth.jsonl, such as examples/holdout")
    ev.add_argument("--offline", action="store_true", help="score the regex baseline instead of Claude")
    ev.add_argument("--model", default="claude-opus-5-5")
    ev.add_argument("--effort", default="low", choices=("low", "medium", "high", "xhigh", "max"))
    ev.add_argument("--limit", type=int)
    ev.add_argument("--workers", type=int, default=4)

    gen = sub.add_parser("generate", help="rebuild the sample invoices from their fixed seeds")
    gen.add_argument("--out", default=str(HERE / "examples"))
    return p


def extractor(args):
    if args.offline:
        return lambda text: baseline.extract(text)
    from .claude import extract

    return lambda text: extract(text, model=args.model, effort=args.effort)[0]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "generate":
            out = Path(args.out)
            generate(out / "known")
            generate(out / "holdout", count=24, seed=12, layouts=HOLDOUT)
            print(f"Wrote {out / 'known'} and {out / 'holdout'}")
            return 0

        run = extractor(args)
        if args.command == "extract":
            inv = run(Path(args.file).read_text())
            print(json.dumps(inv.to_dict(), indent=2, ensure_ascii=False))
            problems = check(inv)
            if problems:
                print("\nNeeds review:", file=sys.stderr)
                for p in problems:
                    print(f"  - {p}", file=sys.stderr)
                return 1
            print("\nAll checks passed.", file=sys.stderr)
            return 0

        cases = load_truth(args.folder)[: args.limit]
        folder = Path(args.folder) / "invoices"

        def one(case):
            try:
                return run((folder / case.file).read_text())
            except Exception as exc:  # noqa: BLE001 - one bad document should not stop the run
                print(f"  {case.file}: {exc}", file=sys.stderr)
                return None

        with ThreadPoolExecutor(max_workers=1 if args.offline else args.workers) as pool:
            results = list(pool.map(one, cases))
        report = Report()
        for case, got in zip(cases, results):
            report.add(case, got)
        print(f"{'Regex baseline' if args.offline else args.model} on {args.folder}\n")
        print(report.as_text())
        return 0
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
