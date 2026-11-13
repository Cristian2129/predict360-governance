"""What GitHub Pages publishes (US-10, B11b). Called by ``.github/workflows/pages.yml``.

- No official demo run yet (no ``runs/official/lineage_log.jsonl``): the fixture, rendered
  with its loud sample banner.
- Otherwise the ``index.html`` of the latest entry of the official log, copied byte for byte,
  only after three checks:
  1. the lineage chain (B5) verifies, each manifest included (``verify_lineage_log``);
  2. ``index.html`` and ``dashboard_data.json`` match the hashes in that run's manifest;
  3. the run is synthetic (a real FinBank run is never published).
  If any check fails nothing is written and the CLI exits 1: the workflow fails, its deploy
  job does not run, and the previous deployment stays online.

Usage:
    python -m src.predict360.publish_pages --out _site [--official-dir runs/official]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from src.predict360.config import ROOT
from src.predict360.dashboard_contract import SAMPLE_PATH
from src.predict360.dashboard_render import write as render_dashboard
from src.predict360.lineage import verify_lineage_log
from src.predict360.run_pipeline import LOG_NAME, OFFICIAL_DIR

OFFICIAL_RUNS = ROOT / "runs" / OFFICIAL_DIR
CHECKED_FILES = ("index.html", "dashboard_data.json")


class PublishRefused(Exception):
    """The official run cannot be published: broken chain, altered files or real data."""


def _latest_official(official_dir: Path) -> tuple[Path, str]:
    log = official_dir / LOG_NAME
    check = verify_lineage_log(log, official_dir)          # the chain and every manifest hash
    if check["status"] != "OK":
        raise PublishRefused("official lineage log does not verify: " + "; ".join(check["problems"][:3]))
    run_id = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])["run_id"]
    run_dir = official_dir / run_id
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    outputs = {o["file"]: o["sha256"] for o in manifest["outputs"]}
    for name in CHECKED_FILES:
        path = run_dir / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != outputs.get(name):
            raise PublishRefused(f"{run_id}/{name} does not match the hash in its manifest")
    if not manifest["synthetic"]:
        raise PublishRefused(f"{run_id} is not synthetic: a real FinBank run is never published")
    return run_dir, run_id


def publish_pages(out_dir: str | Path, official_dir: str | Path = OFFICIAL_RUNS,
                  sample_path: str | Path = SAMPLE_PATH) -> dict:
    out_dir, official_dir = Path(out_dir), Path(official_dir)
    if not (official_dir / LOG_NAME).exists():
        data = json.loads(Path(sample_path).read_text(encoding="utf-8"))
        render_dashboard(data, out_dir / "index.html", publish=True)
        return {"source": "sample", "run_id": None}
    run_dir, run_id = _latest_official(official_dir)        # raises before anything is written
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_bytes((run_dir / "index.html").read_bytes())
    return {"source": "official", "run_id": run_id}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the GitHub Pages site from the official run.")
    parser.add_argument("--out", required=True)
    parser.add_argument("--official-dir", default=str(OFFICIAL_RUNS))
    args = parser.parse_args(argv)
    try:
        result = publish_pages(args.out, args.official_dir)
    except PublishRefused as error:
        print(f"Not published: {error}", file=sys.stderr)
        return 1
    print(f"Published {result['source']}" + (f" run {result['run_id']}" if result["run_id"] else " fixture"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
