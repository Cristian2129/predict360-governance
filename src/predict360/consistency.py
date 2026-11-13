"""Station 11, Gate 3: consistency of every published figure (technical spec, section 9).

Two checks:

1. Manifest against output files. For each registered figure, the output file must still
   exist with the hash recorded in ``outputs`` (nobody edited it after the run), and the
   value at the figure's ``path`` must equal the registered value.
2. Citations against the manifest. ``docs/cited_figures.yaml`` lists, by hand, every figure
   the report and the presentation quote: ``figure_id``, the ``text`` as written, its
   ``locale`` (es | en) and ``where`` it appears. The text must be exactly the figure as
   ``formatting.format_figure`` writes it in that locale.

Without citations (no file, or an empty list) Gate 3 passes with a warning while the team
works; with ``require_citations`` (``--require-citations``, the official demo run) it
fails, because the delivered run cannot pass without checking the report's figures.

Output files are looked up relative to ``run_dir``: the pipeline registers outputs with
``base=run_dir``. Only figures, hashes and texts are read or reported, never client rows.

Re-check a written run after editing the report (prints the report; exit 1 on FAIL; the
run is not modified):
    python -m src.predict360.consistency --run runs/<run_id> [--citations docs/cited_figures.yaml]
        [--require-citations]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import yaml

from src.predict360.config import ROOT
from src.predict360.formatting import LOCALES, format_figure
from src.predict360.lineage import MANIFEST_NAME, resolve_figure_path

CITATIONS_PATH = ROOT / "docs" / "cited_figures.yaml"
CITATION_FIELDS = ("figure_id", "text", "locale", "where")


def _mismatch(figure_id, source, reason, where=None, expected=None, found=None) -> dict:
    return {"figure_id": figure_id, "source": source, "where": where, "expected": expected,
            "found": found, "reason": reason}


def _same_number(expected, found) -> bool:
    numbers = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (expected, found))
    return numbers and math.isclose(expected, found, rel_tol=1e-12, abs_tol=1e-12)


def _check_figures(manifest: dict, run_dir: Path) -> list[dict]:
    outputs = {o["file"]: o for o in manifest["outputs"]}
    documents, mismatches = {}, []
    for figure in manifest["figures"]:
        figure_id, file = figure["figure_id"], figure["file"]
        path = run_dir / file
        if file not in outputs or not path.exists():
            mismatches.append(_mismatch(figure_id, "output_file", "output_missing", where=file))
            continue
        if file not in documents:
            data = path.read_bytes()
            altered = hashlib.sha256(data).hexdigest() != outputs[file]["sha256"]
            try:
                documents[file] = (altered, json.loads(data))
            except ValueError:
                documents[file] = (altered, None)
        altered, document = documents[file]
        if altered:
            mismatches.append(_mismatch(figure_id, "output_file", "output_altered", where=file,
                                        expected=outputs[file]["sha256"]))
            continue
        try:
            found = resolve_figure_path(document, figure["path"])
        except (KeyError, ValueError, TypeError) as error:
            mismatches.append(_mismatch(figure_id, "output_file", "path_not_found", where=f"{file}: {error}"))
            continue
        if not _same_number(figure["value"], found):
            mismatches.append(_mismatch(figure_id, "output_file", "value_differs", where=f"{file}: {figure['path']}",
                                        expected=figure["value"], found=found))
    return mismatches


def load_citations(path: str | Path) -> list:
    path = Path(path)
    if not path.exists():
        return []
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("citations") or []


def _check_citations(manifest: dict, citations: list) -> list[dict]:
    figures = {f["figure_id"]: f for f in manifest["figures"]}
    mismatches = []
    for citation in citations:
        citation = citation if isinstance(citation, dict) else {}
        figure_id, where = citation.get("figure_id"), citation.get("where")
        if (any(not isinstance(citation.get(k), str) or not citation[k].strip() for k in CITATION_FIELDS)
                or citation["locale"] not in LOCALES):
            mismatches.append(_mismatch(figure_id, "citation", "invalid_citation", where=where,
                                        expected=f"fields {list(CITATION_FIELDS)}, locale in {list(LOCALES)}"))
            continue
        if figure_id not in figures:
            mismatches.append(_mismatch(figure_id, "citation", "unknown_figure", where=where, found=citation["text"]))
            continue
        figure = figures[figure_id]
        expected = format_figure(figure["value"], figure["unit"], citation["locale"])
        if citation["text"] != expected:
            mismatches.append(_mismatch(figure_id, "citation", "text_differs", where=where,
                                        expected=expected, found=citation["text"]))
    return mismatches


def run_gate3(manifest: dict, run_dir: str | Path, citations_path: str | Path = CITATIONS_PATH,
              require_citations: bool = False) -> dict:
    citations = load_citations(citations_path)
    mismatches = _check_figures(manifest, Path(run_dir)) + _check_citations(manifest, citations)
    warnings = []
    if not manifest["figures"]:
        warnings.append("no figures registered in the manifest")
    if not citations:
        if require_citations:
            mismatches.append(_mismatch(None, "citations", "no_citations", where=str(citations_path)))
        else:
            warnings.append(f"no citations checked: {Path(citations_path).name} is missing or empty; "
                            "the official run requires them (--require-citations)")
    return {
        "gate": "gate3",
        "status": "FAIL" if mismatches else "PASS",
        "checked": len(manifest["figures"]) + len(citations),
        "figures_checked": len(manifest["figures"]),
        "citations_checked": len(citations),
        "require_citations": require_citations,
        "warnings": warnings,
        "mismatches": mismatches,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate 3: re-check the figures of a written run.")
    parser.add_argument("--run", required=True, help="runs/<run_id> (holds manifest.json and the outputs)")
    parser.add_argument("--citations", default=str(CITATIONS_PATH))
    parser.add_argument("--require-citations", action="store_true")
    args = parser.parse_args(argv)
    run_dir = Path(args.run)
    manifest = json.loads((run_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    report = run_gate3(manifest, run_dir, args.citations, args.require_citations)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
