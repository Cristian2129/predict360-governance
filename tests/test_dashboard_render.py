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
    format_count,
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


def test_the_sample_banner_is_loud_and_comes_first(html):
    # Pages publishes the fixture until the official run exists: nobody may take it for a run
    banner = re.search(r'<div class="([^"]*)" id="banner-sample"[^>]*>(.*?)</div>', html)
    assert banner and "loud" in banner.group(1).split()
    assert "DATOS DE EJEMPLO" in banner.group(2)
    assert html.index('id="banner-sample"') < html.index('id="banner-synthetic"')
    css = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
    assert ".banner.loud" in css


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

# --- trace a figure to its origin (B12b) ------------------------------------------------

def _trace(html, figure_id):
    match = re.search(rf'<details class="trace" data-trace="{re.escape(figure_id)}">(.*?)</details>', html, re.S)
    assert match, f"no trace for {figure_id}"
    return match.group(1)


def _registered(data):
    return {f["figure_id"]: f for f in data["lineage"]["figures"]}


def test_every_traced_figure_is_a_registered_one(html, sample):
    shown = set(re.findall(r'data-figure-id="([^"]+)"', html))
    assert "exposure.delinquency.observed_cop_m" in shown
    assert shown <= set(_registered(sample))
    assert set(re.findall(r'data-trace="([^"]+)"', html)) <= set(_registered(sample))


def test_the_trace_names_file_path_script_commit_and_hashes(html, sample):
    figure = _registered(sample)["exposure.delinquency.observed_cop_m"]
    trace = _trace(html, figure["figure_id"])
    manifest = sample["lineage"]["manifest"]
    output = next(o for o in manifest["outputs"] if o["file"] == figure["file"])
    sources = {s["name"]: s for s in manifest["sources"]}
    for text in (figure["file"], figure["path"], figure["script"], sample["meta"]["commit"], output["sha256"],
                 sources["delinquency"]["file"], sources["delinquency"]["sha256"]):
        assert text in trace
    assert sources["scores"]["sha256"] not in trace          # only the sources this figure comes from


def test_model_figures_trace_to_their_table_and_the_scores(sample):
    data = copy.deepcopy(sample)
    evaluation = next(e for e in data["models"]["evaluations"] if e["status"] == "evaluated" and e["vs_baseline"])
    figure_id = f"models.{evaluation['label']}.{evaluation['model_id']}.difference_vs_baseline_cop_m"
    data["lineage"]["figures"].append({
        "figure_id": figure_id, "value": evaluation["vs_baseline"]["difference_cop_m"], "unit": "COP_m",
        "file": "evaluation.json", "script": "src/predict360/evaluator.py",
        "path": f"evaluations[model_id={evaluation['model_id']},label={evaluation['label']}].vs_baseline.difference_cop_m"})
    html = render(data)
    assert f'data-figure-id="{figure_id}"' in html          # the difference in the verdict table
    trace = _trace(html, figure_id)
    sources = {s["name"]: s["sha256"] for s in data["lineage"]["manifest"]["sources"]}
    assert sources[evaluation["target"]] in trace and sources["scores"] in trace


def test_an_unregistered_figure_is_shown_without_a_trace(sample):
    data = copy.deepcopy(sample)
    data["lineage"]["figures"] = [f for f in data["lineage"]["figures"]
                                  if f["figure_id"] != "exposure.churn.observed_cop_m"]
    html = render(data)
    assert 'data-figure-id="exposure.churn.observed_cop_m"' not in html
    assert format_cop_m(data["exposure"]["tables"]["churn"]["actual_cop_m"]) in html   # the value still shows


# --- the data and lineage view (B12b) ----------------------------------------------------

def _view(html, view_id):
    match = re.search(rf'<section class="view" id="{view_id}">(.*?)</section>', html, re.S)
    assert match, view_id
    return match.group(1)


def test_lineage_view_lists_every_figure_source_and_output(html, sample):
    view = _view(html, "datos")
    assert "Vista en construcción" not in view
    for figure in sample["lineage"]["figures"]:
        assert figure["figure_id"] in view
    for entry in sample["lineage"]["manifest"]["sources"] + sample["lineage"]["manifest"]["outputs"]:
        assert entry["file"] in view and entry["sha256"] in view


def test_lineage_view_says_the_manifest_is_a_snapshot(html):
    assert ("Foto del manifiesto al exportar; el manifiesto final registra también este archivo y el tablero."
            in _view(html, "datos"))


@pytest.mark.parametrize("status,cls,words", [
    ("OK", "ok", "cadena de hashes"),
    ("TAMPERED", "bad", "alterado"),
    ("NOT_CHECKED", "warn", "no se verificó"),
])
def test_the_log_status_is_explained(sample, status, cls, words):
    data = copy.deepcopy(sample)
    data["lineage"]["log_status"] = status
    block = re.search(r'<div class="card" id="log-status">(.*?)</div>', render(data), re.S).group(1)
    assert f'<span class="status {cls}">{status}</span>' in block and words in block


# --- stress view: curve and simulator (B12b-2) -------------------------------------------------

def _evaluated_by_label(data):
    out = {}
    for e in data["models"]["evaluations"]:
        if e["status"] == "evaluated":
            out.setdefault(e["label"], []).append(e)
    return out


def test_stress_view_is_a_hypothetical_scenario_that_never_issues_a_verdict(html):
    view = _view(html, "estres")
    assert "Vista en construcción" not in view
    assert ("Escenario hipotético: no cambia el dictamen, que se fijó con los supuestos registrados en el acta."
            in view)
    assert 'id="sim-reset"' in view and "Restablecer supuestos" in view
    assert "estimación puntual, sin intervalo" in view
    assert "utorizado" not in view                     # neither "Autorizado" nor "No autorizado"


def test_one_curve_per_label_with_models_random_and_k_star(html, sample):
    view = _view(html, "estres")
    for label, evaluations in _evaluated_by_label(sample).items():
        svg = re.search(rf'<svg[^>]*data-curve="{label}"[^>]*>(.*?)</svg>', view, re.S)
        assert svg, label
        for e in evaluations:
            assert f'data-series="{e["model_id"]}"' in svg.group(1)
            assert f'data-kstar="{e["model_id"]}"' in svg.group(1)
        assert 'data-series="random"' in svg.group(1)


def test_the_curve_carries_what_the_simulator_needs_to_redraw_it(html, sample):
    # Every control (capacity, effectiveness, cost) must move the drawing, not only the table
    view = _view(html, "estres")
    for label in _evaluated_by_label(sample):
        svg = re.search(rf'<svg[^>]*data-curve="{label}"[^>]*>', view).group(0)
        for attribute in ("data-x0", "data-xscale", "data-top", "data-plot-h"):
            assert attribute in svg, (label, attribute)
    assert 'data-tick="high"' in view and 'data-tick="low"' in view and 'data-zero="' in view
    assert "se dibujan con los supuestos del acta" not in view


def test_defaults_are_the_evaluator_values_without_javascript(html, sample):
    view = _view(html, "estres")
    for label, evaluations in _evaluated_by_label(sample).items():
        for e in evaluations:
            key = f'{label}.{e["model_id"]}'
            cell = lambda name: re.search(rf'data-sim-{name}="{re.escape(key)}"[^>]*>([^<]*)<', view).group(1)
            assert cell("net") == format_cop_m(e["at_k"]["net_value_cop_m"])
            assert cell("kapplied") == format_count(e["k_applied"])
            assert cell("kstar") == format_count(e["k_star"]["k"])
        random = re.search(rf'data-sim-net="{label}.random"[^>]*>([^<]*)<', view).group(1)
        assert random == format_cop_m(evaluations[0]["random_at_k"]["net_value_cop_m"])


def test_capacity_below_k_star_is_flagged(html, sample):
    view = _view(html, "estres")
    for label, evaluations in _evaluated_by_label(sample).items():
        for e in evaluations:
            flagged = f'data-sim-warning="{label}.{e["model_id"]}"' in view
            assert flagged == (e["k_star"]["k"] > e["k_applied"]), (label, e["model_id"])


def test_simulator_data_and_script_are_inline(html, sample):
    view = _view(html, "estres")
    raw = re.search(r'<script type="application/json" id="sim-data">(.*?)</script>', view, re.S).group(1)
    assert "</" not in raw
    sim = json.loads(raw)
    values = {k: v for item in sample["assumptions"] for k, v in item["value"].items()}
    assert sim["defaults"] == {"capacity_share": values["value.default_capacity_share"],
                               "action_effectiveness": values["value.action_effectiveness"],
                               "loss_given_event": values["value.loss_given_event"],
                               "cost_per_contact_cop": values["value.cost_per_contact_cop"]}
    assert set(sim["labels"]) == set(_evaluated_by_label(sample))
    assert "function appliedPoint" in html and "function selfCheck" in html


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
    for decision in sample["models"]["decisions"]:
        assert f'data-decision="{decision["target"]}"' in html
    assert "No autorizado" in html
    assert "producción" not in html.lower()


@pytest.mark.parametrize("citations,warned", [(0, True), (3, False)])
def test_gate3_pass_without_citations_is_flagged(sample, citations, warned):
    data = copy.deepcopy(sample)
    data["gates"]["gate3"].update(status="PASS", checked=6 + citations, figures_checked=6,
                                  citations_checked=citations)
    assert ('id="gate3-no-citations"' in render(data)) is warned


def _authorized(sample):
    data = copy.deepcopy(sample)
    data["models"]["decisions"][0].update(verdict="authorized_for_shadow_deployment",
                                          reason_code="authorized", model_id="model_a")
    return data


def test_authorized_verdict_is_shown_as_shadow_deployment(sample):
    html = render(_authorized(sample))
    assert "Autorizado a despliegue en sombra" in html
    assert "producción" not in html.lower()


@pytest.mark.parametrize("code,label", [
    ("insufficient_evidence", "Evidencia insuficiente"),
    ("does_not_beat_baseline", "No supera la regla"),
    ("no_baseline", "Sin regla base comparable"),
])
def test_reason_code_label(sample, code, label):
    data = copy.deepcopy(sample)
    data["models"]["decisions"][0]["reason_code"] = code
    assert label in render(data)


def test_decision_shows_point_difference_next_to_the_paired_interval(sample, html):
    compared = [e for e in sample["models"]["evaluations"] if e["status"] == "evaluated" and e["vs_baseline"]]
    assert compared
    for e in compared:
        vs = e["vs_baseline"]
        row = f'data-comparison="{e["target"]}.{e["label"]}.{e["model_id"]}"'
        assert row in html
        fragment = html[html.index(row):html.index("</tr>", html.index(row))]
        for value in (vs["difference_cop_m"], vs["ci_low_cop_m"], vs["ci_high_cop_m"]):
            assert format_cop_m(value) in fragment


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


def test_pages_workflow_publishes_with_the_publish_guard(sample, tmp_path):
    # B11b: the workflow goes through publish_pages, which renders the fixture with publish=True
    from src.predict360.publish_pages import publish_pages
    workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    assert "src.predict360.publish_pages" in workflow and "actions/deploy-pages" in workflow
    real = copy.deepcopy(sample)
    real["meta"]["synthetic"] = False
    path = tmp_path / "real.json"
    path.write_text(json.dumps(real), encoding="utf-8")
    with pytest.raises(ValueError, match="synthetic"):
        publish_pages(tmp_path / "_site", official_dir=tmp_path / "none", sample_path=path)
