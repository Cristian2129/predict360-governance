"""Tests for publish_pages.py: what GitHub Pages publishes (US-10, B11b).

- While there is no official demo run, the fixture, with its loud sample banner.
- Once runs/official/ exists, the page of its latest run, byte for byte, only after the
  lineage chain (B5) and the page hashes check out. Otherwise nothing is published, the
  workflow fails and the previous deployment stays online.
"""
import json
from datetime import date, datetime, timezone

import pytest
import yaml

from src.predict360.config import CONFIG_DIR, ROOT
from src.predict360.publish_pages import PublishRefused, main, publish_pages
from src.predict360.run_pipeline import run_pipeline

SYNTHETIC = CONFIG_DIR / "synthetic.yaml"
COMMIT = "c" * 40
AS_OF = date(2026, 11, 14)
HOURS = ("date,person,sprint,story_id,hours,estimated,note\n"
         "2026-10-30,Cristian Vega,2,US-07,12,1,reconstructed\n")


def _official(tmp_path, minute=0):
    cfg = yaml.safe_load(SYNTHETIC.read_text(encoding="utf-8"))
    (tmp_path / "hours_log.csv").write_text(HOURS, encoding="utf-8")
    cfg["management"]["hours_log"] = str(tmp_path / "hours_log.csv")
    config = tmp_path / "synthetic.yaml"
    config.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    citations = tmp_path / "cited_figures.yaml"
    citations.write_text(yaml.safe_dump({"version": "v1", "citations": [
        {"figure_id": "exposure.delinquency.observed_cop_m", "text": "COP 58.800 M", "locale": "es",
         "where": "slide 2"}]}, allow_unicode=True), encoding="utf-8")
    result = run_pipeline(config, official=True, citations_path=citations, runs_dir=tmp_path / "runs",
                          commit=COMMIT, now=datetime(2026, 11, 14, 18, minute, tzinfo=timezone.utc), as_of=AS_OF)
    assert result["official"] is True
    return result


@pytest.fixture(scope="module")
def two_runs(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("pages")
    first = _official(tmp_path, minute=0)
    second = _official(tmp_path, minute=5)
    return tmp_path / "runs" / "official", first, second


def test_without_an_official_run_the_fixture_is_published(tmp_path):
    result = publish_pages(tmp_path / "_site", official_dir=tmp_path / "runs" / "official")
    assert result == {"source": "sample", "run_id": None}
    html = (tmp_path / "_site" / "index.html").read_text(encoding="utf-8")
    assert 'id="banner-sample"' in html


def test_the_latest_official_run_is_published_byte_for_byte(two_runs, tmp_path):
    official, first, second = two_runs
    result = publish_pages(tmp_path / "_site", official_dir=official)
    assert result == {"source": "official", "run_id": second["run_id"]}
    assert (tmp_path / "_site" / "index.html").read_bytes() == (second["run_dir"] / "index.html").read_bytes()


def test_a_broken_chain_publishes_nothing(two_runs, tmp_path):
    official, _, _ = two_runs
    copy = tmp_path / "official"
    copy.mkdir()
    for path in official.rglob("*"):
        target = copy / path.relative_to(official)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
    log = copy / "lineage_log.jsonl"
    lines = log.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    entry["closed_at"] = "2026-11-14T17:00:00Z"                      # someone edits history
    log.write_text("\n".join([json.dumps(entry, sort_keys=True, separators=(",", ":"))] + lines[1:]) + "\n",
                   encoding="utf-8")
    with pytest.raises(PublishRefused, match="lineage"):
        publish_pages(tmp_path / "_site", official_dir=copy)
    assert not (tmp_path / "_site").exists()


def test_a_page_altered_after_the_run_publishes_nothing(two_runs, tmp_path):
    official, _, second = two_runs
    page = second["run_dir"] / "index.html"
    original = page.read_bytes()
    try:
        page.write_bytes(original.replace(b"</footer>", b" edited</footer>"))
        with pytest.raises(PublishRefused, match="index.html"):
            publish_pages(tmp_path / "_site", official_dir=official)
    finally:
        page.write_bytes(original)
    assert not (tmp_path / "_site").exists()


def test_cli_fails_when_publishing_is_refused(two_runs, tmp_path):
    official, _, second = two_runs
    assert main(["--out", str(tmp_path / "ok"), "--official-dir", str(official)]) == 0
    assert main(["--out", str(tmp_path / "bad"), "--official-dir", str(tmp_path / "missing")]) == 0  # fixture
    page = second["run_dir"] / "dashboard_data.json"
    original = page.read_bytes()
    try:
        page.write_bytes(original + b" ")
        assert main(["--out", str(tmp_path / "refused"), "--official-dir", str(official)]) == 1
    finally:
        page.write_bytes(original)


def test_the_pages_workflow_publishes_through_the_checks():
    workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    assert "src.predict360.publish_pages" in workflow
    assert "dashboard_data.sample.json" not in workflow         # the fallback lives in publish_pages
    assert "needs: build" in workflow                            # a failed build never deploys
