"""Tests for the static dashboard renderer (technical spec, section 11; US-10).

One self-contained index.html, rendered in Python from dashboard_data.json: it opens with a
double click, without network, and from GitHub Pages. Visual checks (projector and phone)
are manual and live in the PR checklist.
"""
import copy
import json
import os
import re
import subprocess
import sys

import pytest

from src.predict360.config import ROOT
from src.predict360.dashboard_contract import SAMPLE_PATH
from src.predict360.dashboard_render import (
    GUIDED_STEPS,
    TABS,
    format_cop_m,
    format_pct,
    render,
    write,
)


@pytest.fixture(scope="module")
def sample():
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def html(sample):
    return render(sample)


def _ids(html):
    return set(re.findall(r'\bid="([^"]+)"', html))


# --- number formatting (es-CO, display only) ----------------------------------------

@pytest.mark.parametrize("value,expected", [
    (58800.0, "COP 58.800 M"),
    (18200.000004, "COP 18.200 M"),
    (168.333333, "COP 168,3 M"),
    (-92.24, "COP -92,2 M"),
    (0.833333, "COP 0,8 M"),
    (None, "—"),
])
def test_format_cop_m_uses_colombian_notation(value, expected):
    assert format_cop_m(value) == expected


@pytest.mark.parametrize("value,expected", [(0.279, "27,9 %"), (1.0, "100,0 %"), (None, "—")])
def test_format_pct(value, expected):
    assert format_pct(value) == expected


# --- one self-contained file ----------------------------------------------------------

def test_single_file_without_external_resources(html):
    assert html.startswith("<!doctype html>")
    assert "<style>" in html
    assert not re.search(r"<script[^>]*\bsrc=", html)
    assert not re.search(r"<link[^>]*stylesheet", html)
    assert not re.search(r'(src|href)="(https?:)?//', html)   # no CDN, fonts or remote images
    assert '<meta name="viewport"' in html                   # responsive from B12a
    assert '<html lang="es">' in html


def test_render_validates_the_contract_first(sample):
    broken = copy.deepcopy(sample)
    del broken["exposure"]
    with pytest.raises(ValueError, match="dashboard_data_v1"):
        render(broken)


# --- banners ------------------------------------------------------------------------

def test_sample_synthetic_and_simulated_banners(html):
    assert 'id="banner-synthetic"' in html
    assert 'id="banner-sample"' in html
    assert 'id="banner-simulated"' in html


def test_no_sample_banner_for_a_real_pipeline_run(sample):
    run = copy.deepcopy(sample)
    run["meta"]["sample"] = False
    html = render(run)
    assert 'id="banner-sample"' not in html and 'id="banner-synthetic"' in html


@pytest.mark.parametrize("commit,warned", [
    ("a" * 40, False), ("a" * 40 + "-dirty", True), ("unknown", True),
])
def test_commit_warning_on_dirty_or_unknown(sample, commit, warned):
    data = copy.deepcopy(sample)
    data["meta"]["commit"] = commit
    assert ('id="banner-commit"' in render(data)) is warned


# --- navigation: tabs and 6-step guided mode -----------------------------------------

def test_the_six_views_of_the_spec_exist(html):
    assert [tab_id for tab_id, _ in TABS] == ["resumen", "datos", "modelos", "estres", "gestion", "entrega"]
    ids = _ids(html)
    for tab_id, _ in TABS:
        assert tab_id in ids and f'href="#{tab_id}"' in html


def test_guided_mode_has_six_steps_linked_to_existing_views(html):
    assert len(GUIDED_STEPS) == 6
    ids, tabs = _ids(html), {tab_id for tab_id, _ in TABS}
    for number, step in enumerate(GUIDED_STEPS, start=1):
        assert f"guia-{number}" in ids
        assert step["tab"] in tabs
        assert f'href="#{step["tab"]}"' in html
    assert 'href="#guia-2"' in html   # next-step links


# --- summary: every figure comes from the JSON ----------------------------------------

def test_summary_shows_exposure_from_the_json_with_figure_ids(sample, html):
    for table in ("delinquency", "churn"):
        rec = sample["exposure"]["tables"][table]
        assert format_cop_m(rec["actual_cop_m"]) in html
        assert format_cop_m(rec["expected_cop_m"]) in html
        assert f'data-figure-id="exposure.{table}.observed_cop_m"' in html


def test_changing_the_json_changes_the_page(sample):
    data = copy.deepcopy(sample)
    data["exposure"]["tables"]["delinquency"]["actual_cop_m"] = 12345.6
    assert "COP 12.346 M" in render(data)


def test_summary_shows_gates_run_and_verdicts(sample, html):
    assert sample["meta"]["run_id"] in html
    assert sample["meta"]["commit"][:12] in html
    for gate in ("gate1", "gate2", "gate3"):
        assert f'data-gate="{gate}"' in html
    assert "Autorizado a despliegue en sombra" in html
    assert "producción" not in html.lower()


def test_renderer_source_has_no_hand_written_figures():
    source = (ROOT / "src" / "predict360" / "dashboard_render.py").read_text(encoding="utf-8")
    for figure in ("58800", "58.800", "18200", "18.200", "77000", "77.000", "118", "180", "160", "42.5", "42,5"):
        assert figure not in source, figure


def test_text_from_the_json_is_escaped(sample):
    data = copy.deepcopy(sample)
    data["models"]["decisions"][0]["reason"] = "<script>alert(1)</script>"
    html = render(data)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


# --- writing and publishing -------------------------------------------------------------

def test_write_creates_index_html(sample, tmp_path):
    path = write(sample, tmp_path / "site" / "index.html")
    assert path.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_publishing_refuses_non_synthetic_data(sample, tmp_path):
    real = copy.deepcopy(sample)
    real["meta"]["synthetic"] = False
    write(real, tmp_path / "local.html")                 # inside FinBank: local use is fine
    with pytest.raises(ValueError, match="synthetic"):
        write(real, tmp_path / "public.html", publish=True)


def test_cli_renders_the_fixture(tmp_path):
    out = tmp_path / "_site" / "index.html"
    proc = subprocess.run([sys.executable, "-m", "src.predict360.dashboard_render", "--data", str(SAMPLE_PATH),
                           "--out", str(out), "--publish"], cwd=ROOT, capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert proc.returncode == 0, proc.stderr
    assert out.exists()


def test_pages_workflow_publishes_with_the_publish_guard():
    workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    assert "src.predict360.dashboard_render" in workflow and "--publish" in workflow
    assert "actions/deploy-pages" in workflow
