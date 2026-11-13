"""Run manifest and tamper-evident lineage log (technical spec, section 5).

Each run writes ``runs/<run_id>/manifest.json`` and appends one line to
``runs/lineage_log.jsonl``. The manifest holds hashes, row counts, gate results,
waivers and the registry of figures, never client rows.

Lineage log: each entry stores ``prev_entry_sha256`` (the hash of the previous line;
null for the first one), so ``verify_lineage_log`` detects an edited or deleted line.
This is tamper-EVIDENT, not tamper-proof: whoever rewrites the whole file can recompute
the chain. To close that gap, each manifest stores ``lineage_head_sha256`` (the last log
entry when it was written), so a recomputed chain no longer matches the manifests
already written. A versioned copy (a git commit) of the official run is the outside witness.

A manifest is closed when written: it cannot be overwritten, and figures or outputs
cannot be added afterwards. Figures keep full precision; rounding is for display only.

Each figure stores the ``path`` of its value inside its output file, so Gate 3 can read it
back. Paths use keys and selectors by identifier, never list positions, so reordering a
list cannot make a figure point to another item:
``evaluations[model_id=model_b,label=delinquency_60].at_k.net_value_cop_m``.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from src.predict360 import __version__
from src.predict360.config import ROOT

FIGURE_ID = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
MANIFEST_NAME = "manifest.json"
_CONDITION = r"[A-Za-z0-9_]+=[A-Za-z0-9_\-]+"
_PATH_SEGMENT = re.compile(rf"^(?P<key>[A-Za-z0-9_]+)(?:\[(?P<select>{_CONDITION}(?:,{_CONDITION})*)\])?$")


def _parse_figure_path(path: str) -> list[tuple[str, dict]]:
    """Segments of a figure path: (key, {field: value}) with an empty dict when there is no selector."""
    segments = []
    for segment in (path or "").split("."):
        match = _PATH_SEGMENT.match(segment)
        if not match:
            raise ValueError(f"invalid figure path {path!r}: use keys and [field=value] selectors, "
                             "e.g. evaluations[model_id=model_b,label=delinquency_60].at_k.net_value_cop_m")
        select = dict(c.split("=", 1) for c in match["select"].split(",")) if match["select"] else {}
        segments.append((match["key"], select))
    return segments


def resolve_figure_path(document, path: str):
    """The value at ``path``. A list can only be entered with a selector that matches exactly one item."""
    node = document
    for key, select in _parse_figure_path(path):
        if not isinstance(node, dict):
            raise ValueError(f"{path!r}: {key!r} is applied to a list; lists need a [field=value] selector, "
                             "not a position")
        if key not in node:
            raise KeyError(f"{path!r}: key {key!r} not found")
        node = node[key]
        if select:
            if not isinstance(node, list):
                raise ValueError(f"{path!r}: selector on {key!r}, which is not a list")
            matches = [item for item in node if isinstance(item, dict)
                       and all(str(item.get(field)) == value for field, value in select.items())]
            if len(matches) != 1:
                raise ValueError(f"{path!r}: selector on {key!r} matched {len(matches)} items, not exactly one")
            node = matches[0]
    return node


def _utc(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _iso(now: datetime) -> str:
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def new_run_id(now: datetime | None = None, suffix: str | None = None) -> str:
    """``20261112T1530-a1b2c3``: UTC minute plus 6 random hex characters."""
    return f"{_utc(now):%Y%m%dT%H%M}-{suffix or secrets.token_hex(3)}"


def git_commit(cwd: str | Path = ROOT) -> str:
    """HEAD sha, ``<sha>-dirty`` with uncommitted changes to tracked files, or ``unknown``
    when there is no git (e.g. code shipped as a zip). Never fails the run."""
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True,
                             text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=cwd,
                               capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{sha}-dirty" if dirty else sha


def file_entry(path: str | Path, base: str | Path = ROOT) -> dict:
    """Hash, size and (for CSV) data rows of a file. Never its content."""
    path = Path(path)
    data = path.read_bytes()
    try:
        name = path.resolve().relative_to(Path(base).resolve()).as_posix()
    except ValueError:
        name = path.name
    rows = max(data.count(b"\n") - 1, 0) if path.suffix == ".csv" else None
    return {"file": name, "sha256": _sha256_bytes(data), "rows": rows, "bytes": len(data)}


def start_manifest(cfg: dict, config_path: str | Path, run_id: str | None = None,
                   now: datetime | None = None, commit: str | None = None) -> dict:
    now = _utc(now)
    return {
        "run_id": run_id or new_run_id(now),
        "config": Path(config_path).name,
        "synthetic": cfg["synthetic"],
        "commit": commit if commit is not None else git_commit(),
        "code_version": __version__,
        "created_at": _iso(now),
        "snapshot_date": str(cfg["snapshot_date"]),
        "sources": [],
        "contract_versions": {},
        "gates": {},
        "waivers": [],
        "scores_sha256": None,
        "parameters": {"horizons": cfg["horizons_days"], "seed": cfg["seed"]},
        "outputs": [],
        "figures": [],
    }


def _check_open(manifest: dict) -> None:
    if "closed_at" in manifest:
        raise ValueError(f"manifest {manifest['run_id']} is closed: it was already written")


def add_source(manifest: dict, name: str, path: str | Path, base: str | Path = ROOT) -> dict:
    _check_open(manifest)
    entry = {"name": name, **file_entry(path, base)}
    manifest["sources"].append(entry)
    if name == "scores":
        manifest["scores_sha256"] = entry["sha256"]
    return entry


def record_gate(manifest: dict, report: dict, cfg: dict) -> None:
    """Gate status (global, per table and counts when the report has them), contract versions
    and the full record of every waiver applied."""
    _check_open(manifest)
    gate = {"status": report["status"]}
    if "tables" in report:
        gate["tables"] = {name: table["status"] for name, table in report["tables"].items()}
    if "counts" in report:
        gate["counts"] = report["counts"]
    manifest["gates"][report["gate"]] = gate
    manifest["contract_versions"].update(report.get("contract_versions") or {})
    known = {w["id"]: w for w in cfg.get("waivers") or []}
    recorded = {w["id"] for w in manifest["waivers"]}
    for waiver_id in report.get("waivers_applied") or []:
        if waiver_id not in recorded:
            manifest["waivers"].append(known[waiver_id])
            recorded.add(waiver_id)


def add_output(manifest: dict, path: str | Path, base: str | Path) -> dict:
    """Registers a file the run produced; figures point to it by ``file``."""
    _check_open(manifest)
    entry = file_entry(path, base)
    manifest["outputs"].append(entry)
    return entry


def register_figure(manifest: dict, figure_id: str, value, unit: str, file: str, script: str,
                    path: str) -> dict:
    """Origin of a published figure. ``file`` must be an output (its hash lives in outputs) and
    ``path`` locates the value inside it (see the module docstring)."""
    _check_open(manifest)
    if not FIGURE_ID.match(figure_id):
        raise ValueError(f"figure_id must be dotted lowercase (e.g. exposure.delinquency.observed_cop_m): "
                         f"{figure_id!r}")
    if any(f["figure_id"] == figure_id for f in manifest["figures"]):
        raise ValueError(f"figure {figure_id} is already registered")
    if not any(o["file"] == file for o in manifest["outputs"]):
        raise ValueError(f"figure {figure_id} points to {file}, which is not in outputs")
    _parse_figure_path(path)
    figure = {"figure_id": figure_id, "value": value, "unit": unit, "file": file, "script": script, "path": path}
    manifest["figures"].append(figure)
    return figure


def _last_line(log_path: Path) -> str | None:
    if not log_path.exists():
        return None
    lines = log_path.read_text(encoding="utf-8").splitlines()
    return lines[-1] if lines else None


def write_manifest(manifest: dict, runs_dir: str | Path, log_path: str | Path,
                   now: datetime | None = None) -> Path:
    """Closes the manifest, writes it (never over an existing one) and appends the log entry."""
    _check_open(manifest)
    runs_dir, log_path = Path(runs_dir), Path(log_path)
    path = runs_dir / manifest["run_id"] / MANIFEST_NAME
    if path.exists():
        raise FileExistsError(f"{path} already exists: a manifest is never overwritten")
    head_line = _last_line(log_path)
    manifest["lineage_head_sha256"] = None if head_line is None else _sha256_bytes(head_line.encode("utf-8"))
    manifest["closed_at"] = _iso(_utc(now))

    text = json.dumps(manifest, indent=2, ensure_ascii=False, default=str) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")

    entry = {
        "run_id": manifest["run_id"],
        "closed_at": manifest["closed_at"],
        "manifest": f"{manifest['run_id']}/{MANIFEST_NAME}",
        "manifest_sha256": _sha256_bytes(text.encode("utf-8")),
        "prev_entry_sha256": manifest["lineage_head_sha256"],
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", newline="\n") as handle:   # append only
        handle.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")
    return path


def verify_lineage_log(log_path: str | Path, runs_dir: str | Path | None = None) -> dict:
    """OK or TAMPERED. Checks the hash chain and, with ``runs_dir``, each manifest's hash
    and its ``lineage_head_sha256`` anchor."""
    problems = []
    lines = Path(log_path).read_text(encoding="utf-8").splitlines()
    prev, seen = None, set()
    for number, line in enumerate(lines, start=1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            problems.append(f"line {number}: not valid JSON")
            prev = _sha256_bytes(line.encode("utf-8"))
            continue
        if entry.get("prev_entry_sha256") != prev:
            problems.append(f"line {number}: prev_entry_sha256 does not match the previous line")
        if entry.get("run_id") in seen:
            problems.append(f"line {number}: duplicate run_id {entry.get('run_id')}")
        seen.add(entry.get("run_id"))
        if runs_dir is not None:
            path = Path(runs_dir) / entry.get("manifest", "")
            if not path.is_file():
                problems.append(f"line {number}: manifest {entry.get('manifest')} not found")
            else:
                data = path.read_bytes()
                if _sha256_bytes(data) != entry.get("manifest_sha256"):
                    problems.append(f"line {number}: manifest_sha256 does not match {entry['manifest']}")
                try:
                    head = json.loads(data).get("lineage_head_sha256")
                except json.JSONDecodeError:
                    head = "invalid"
                if head != entry.get("prev_entry_sha256"):
                    problems.append(f"line {number}: lineage_head_sha256 in {entry['manifest']} "
                                    "does not match the log")
        prev = _sha256_bytes(line.encode("utf-8"))
    return {"status": "TAMPERED" if problems else "OK", "entries": len(lines), "problems": problems}
