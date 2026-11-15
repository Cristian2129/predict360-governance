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
from src.predict360.formatting import format_ratio
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


def _demo_note(html):
    match = re.search(r'<p class="note" data-demo-card="([^"]+)">(.*?)</p>', html, re.S)
    return match and (match.group(1), match.group(2))


def test_a_demo_card_is_labelled_next_to_its_rejection_reason(sample, html):
    # «6 admitidas · 1 rechazada» alone could read as a team handing in a leaky model
    demo = next(c for c in sample["models"]["cards"] if c["demo"])
    file, text = _demo_note(html)
    assert file == demo["file"]
    assert "Ficha de demostración" in text and "partición no temporal" in text
    assert "temporal_split" in text and _e_model(demo) in text
    gate2 = html[html.index('data-gate="gate2"'):html.index('data-gate="gate3"')]
    assert "1 de demostración" in gate2


def _e_model(card):
    return f'{card["target"]} · {card["model_id"]}'


def test_without_demo_cards_there_is_no_demo_label(sample):
    data = copy.deepcopy(sample)
    for card in data["models"]["cards"]:
        card["demo"] = False
    page = render(data)
    assert _demo_note(page) is None and "de demostración" not in page


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


# --- data view (B12c-3): can the data of this run be trusted? ---------------------------------

DATA_TABLES = ("delinquency", "churn", "scores")


def _data(data):
    return _view(render(data), "datos")


def test_data_comes_before_lineage(html):
    view = _view(html, "datos")
    assert view.index('id="data-verdict"') < view.index('id="log-status"')


@pytest.mark.parametrize("status,cls,words", [("PASS_WITH_WAIVERS", "warn", "waiver"), ("FAIL", "bad", "no pasan"),
                                              ("PASS", "ok", "cumplen")])
def test_the_data_verdict_is_said_in_plain_words(sample, status, cls, words):
    data = copy.deepcopy(sample)
    tables = data["gates"]["gate1"]["tables"]
    if status == "FAIL":
        tables["scores"].update(status="FAIL", failed_rules=[{"rule": "expect_column_values_to_be_between",
                                "column": "score", "critical": True, "unexpected_count": 2, "unexpected_pct": 0.1,
                                "waived_by": None}])
        data["gates"]["gate1"]["status"] = "FAIL"
    if status == "PASS":
        tables["churn"].update(status="PASS", failed_rules=[])
    card = re.search(r'<div class="card" id="data-verdict">(.*?)</div>', _data(data), re.S).group(1)
    plain = re.search(r'<p class="plain">(.*?)</p>', card, re.S).group(1)
    assert f'class="status {cls}"' in plain and words in plain


def test_gate1_lists_the_data_tables_but_not_the_hours_log(sample, html):
    view = _view(html, "datos")
    for table in DATA_TABLES:
        assert f'data-gate1-table="{table}"' in view
    assert 'data-gate1-table="hours_log"' not in view and "hours_log" not in view.split('id="log-status"')[0]
    rule = sample["gates"]["gate1"]["tables"]["churn"]["failed_rules"][0]
    row = re.search(r'<tr data-gate1-table="churn">(.*?)</tr>', view, re.S).group(1)
    assert rule["column"] in row and rule["waived_by"] in row


def test_the_hours_log_gate_is_in_the_management_view(sample, html):
    view = _view(html, "gestion")
    assert 'data-gate1-table="hours_log"' in view
    data = copy.deepcopy(sample)
    data["management"] = {"status": "NOT_RUN", "reason": "hours_log failed Gate 1"}
    data["gates"]["gate1"]["tables"]["hours_log"].update(status="FAIL")
    assert 'data-gate1-table="hours_log"' in _management(data)    # it says why management did not run


def test_a_table_level_rule_without_a_share_is_shown(sample):
    data = copy.deepcopy(sample)
    data["gates"]["gate1"]["tables"]["scores"].update(status="FAIL", rows=0, failed_rules=[
        {"rule": "expect_table_row_count_to_be_between", "column": None, "critical": True,
         "unexpected_count": None, "unexpected_pct": None, "waived_by": None}])
    row = re.search(r'<tr data-gate1-table="scores">(.*?)</tr>', _data(data), re.S).group(1)
    assert "expect_table_row_count_to_be_between" in row and "None" not in row


def _missing_rows(view):
    return dict(re.findall(r'<tr data-missing="([^"]+)">(.*?)</tr>', view, re.S))


def test_missing_lists_only_columns_with_a_contract_limit(sample, html):
    rows = _missing_rows(_view(html, "datos"))
    expected = {f"{t}.{c}" for t in DATA_TABLES for c, m in sample["quality"]["missing"][t].items()
                if m["limit_pct"] is not None}
    assert set(rows) == expected
    assert "delinquency.first_delinquency_date" not in rows and "churn.cancellation_date" not in rows
    assert "W-01" in rows["churn.tenure_months"] and 'class="status warn"' in rows["churn.tenure_months"]
    assert 'class="status ok"' in rows["delinquency.client_id"]


def test_a_column_over_its_limit_without_a_waiver_is_red(sample):
    data = copy.deepcopy(sample)
    data["quality"]["missing"]["delinquency"]["tenure_months"].update(count=50, pct=10.0)
    row = _missing_rows(_data(data))["delinquency.tenure_months"]
    assert 'class="status bad"' in row


def test_the_waiver_is_explained_in_plain_words_with_its_expiry(sample, html):
    view = _view(html, "datos")
    waiver = sample["quality"]["waivers"][0]
    card = re.search(rf'<div class="card" data-waiver="{waiver["id"]}">(.*?)</div>', view, re.S).group(1)
    pct = sample["quality"]["missing"][waiver["table"]][waiver["column"]]["pct"]
    plain = re.search(r'<p class="plain">(.*?)</p>', card, re.S).group(1)
    assert f"El {format_pct(pct / 100)}" in plain and "antigüedad" in plain and "no se rellena, se evalúa aparte" in plain
    assert waiver["expires"] in card and waiver["approved_by"] in card and waiver["risk"] in card


@pytest.mark.parametrize("generated_at,soon", [("2026-11-14T08:00:00Z", True), ("2026-09-01T08:00:00Z", False)])
def test_a_waiver_close_to_expiry_is_flagged(sample, generated_at, soon):
    data = copy.deepcopy(sample)
    data["meta"]["generated_at"] = generated_at
    assert ('data-waiver-expiring="W-01"' in _data(data)) is soon


def test_the_funnel_has_every_step_with_proportional_bars(sample, html):
    view = _view(html, "datos")
    for target, funnel in sample["quality"]["labeling_funnel"].items():
        block = re.search(rf'<div class="card" data-funnel="{target}">(.*?)</table>', view, re.S).group(1)
        assert len(re.findall(r"<tr data-step=", block)) == len(funnel["steps"])
        total = funnel["steps"][0]["clients"]
        for step in funnel["steps"]:
            row = re.search(rf'<tr data-step="{step["step"]}">(.*?)</tr>', block, re.S).group(1)
            if step.get("status") == "not_verifiable":
                assert step["missing_column"] in row and f"{target}_v2" in row and "No verificable" in row
            else:
                width = float(re.search(r'style="width: ([\d.]+)%"', row).group(1))
                assert width == pytest.approx(100 * step["clients"] / total, abs=0.05)


def test_each_horizon_is_explained_in_plain_words(sample, html):
    view = _view(html, "datos")
    for target, funnel in sample["quality"]["labeling_funnel"].items():
        total = funnel["steps"][0]["clients"]
        for label, h in funnel["horizons"].items():
            plain = re.search(rf'<p class="plain" data-horizon="{label}">(.*?)</p>', view, re.S).group(1)
            assert f"De {format_count(total)} clientes, {format_count(h['mature_clients'])}" in plain
            assert format_count(total - h["mature_clients"]) in plain and "aún no se sabe" in plain
            assert format_pct(h["base_rate"]) in plain


# --- models view (B12c-2): which model ranks best, and is the evidence enough? ----------------

def _models(data):
    return _view(render(data), "modelos")


def _attr(tag, name):
    return re.search(rf'\b{name}="([^"]*)"', tag).group(1)


def test_models_view_is_built_and_never_says_production(html):
    view = _view(html, "modelos")
    assert "Vista en construcción" not in view and "producción" not in view.lower()


def test_the_global_verdict_comes_first(sample, html):
    view = _view(html, "modelos")
    verdict = re.search(r'<div class="card" id="models-verdict">(.*?)</div>', view, re.S)
    assert verdict and view.index('id="models-verdict"') < view.index("data-decision-card=")
    assert "No autorizado" in verdict.group(1)            # the fixture authorizes nothing


@pytest.mark.parametrize("code,tag", [("insufficient_evidence", "Evidencia insuficiente"),
                                      ("authorized", "Supera la regla"),
                                      ("does_not_beat_baseline", "No supera la regla")])
def test_the_target_tag_comes_from_the_reason_of_the_decision(sample, code, tag):
    data = copy.deepcopy(sample)
    decision = next(d for d in data["models"]["decisions"] if d["target"] == "delinquency")
    decision["reason_code"] = code
    if code == "authorized":
        decision.update(verdict="authorized_for_shadow_deployment", model_id="model_a")
    card = re.search(r'<div class="card" data-decision-card="delinquency">(.*?)</svg>', _models(data), re.S).group(1)
    assert re.search(rf'<span class="status \w+" data-decision-tag="delinquency">{tag}</span>', card)


def _ci_rows(view):
    return re.findall(r'<g data-ci="([^"]+)"[^>]*>(.*?)</g>', view, re.S)


def test_the_drawn_interval_matches_the_evaluation(sample, html):
    view = _view(html, "modelos")
    expected = {f'{e["label"]}.{e["model_id"]}': e["vs_baseline"] for e in sample["models"]["evaluations"]
                if e["status"] == "evaluated" and e["vs_baseline"]}
    rows = dict(_ci_rows(view))
    assert set(rows) == set(expected)
    for svg in re.findall(r'<svg class="ci"[^>]*>.*?</svg>', view, re.S):
        head = svg[:svg.index(">")]
        vmin, x0, scale = (float(_attr(head, n)) for n in ("data-vmin", "data-x0", "data-xscale"))
        px = lambda v: x0 + (v - vmin) * scale
        for key, body in re.findall(r'<g data-ci="([^"]+)"[^>]*>(.*?)</g>', svg, re.S):
            vs = expected[key]
            line = re.search(r"<line class=\"ci-range\"[^>]*>", body).group(0)
            dot = re.search(r"<circle class=\"ci-point\"[^>]*>", body).group(0)
            assert float(_attr(line, "x1")) == pytest.approx(px(vs["ci_low_cop_m"]), abs=0.01)
            assert float(_attr(line, "x2")) == pytest.approx(px(vs["ci_high_cop_m"]), abs=0.01)
            assert float(_attr(dot, "cx")) == pytest.approx(px(vs["difference_cop_m"]), abs=0.01)
        zero = re.search(r'<line class="zero"[^>]*>', svg).group(0)
        assert float(_attr(zero, "x1")) == pytest.approx(px(0.0), abs=0.01)
        shade = re.search(r'<rect class="rule-better"[^>]*>', svg).group(0)
        assert float(_attr(shade, "x")) + float(_attr(shade, "width")) == pytest.approx(px(0.0), abs=0.01)
        assert "la regla es mejor" in svg


def test_delinquency_must_win_at_30_and_60_days(html):
    card = re.search(r'data-decision-card="delinquency">(.*?)</p>', _view(html, "modelos"), re.S).group(1)
    assert "30 y a 60 días" in card


def test_a_target_without_a_comparison_says_so(sample, html):
    card = re.search(r'data-decision-card="churn">(.*?)</div>', _view(html, "modelos"), re.S).group(1)
    assert 'id="ci-none-churn"' in card                     # fixture: churn baseline not evaluated


def _capture_svgs(view):
    return re.findall(r'(<svg class="capture"[^>]*>)(.*?)</svg>', view, re.S)


def test_one_capture_curve_per_label_behind_a_selector(sample, html):
    view = _view(html, "modelos")
    labels = sorted({e["label"] for e in sample["models"]["evaluations"] if e["status"] == "evaluated"})
    assert sorted(_attr(head, "data-capture-curve") for head, _ in _capture_svgs(view)) == labels
    assert sorted(re.findall(r'<input type="radio" name="capture-label" id="capture-([^"]+)"', view)) == labels
    assert "data-curve=" not in view                        # the simulator only redraws the Estrés curves


def test_the_capture_curve_ends_at_100_and_the_diagonal_is_exact(sample, html):
    evaluations = [e for e in sample["models"]["evaluations"] if e["status"] == "evaluated"]
    for head, body in _capture_svgs(_view(html, "modelos")):
        x0, y0, w, h = (float(_attr(head, n)) for n in ("data-x0", "data-y0", "data-w", "data-h"))
        diagonal = re.search(r'<line class="diagonal"[^>]*>', body).group(0)
        assert [float(_attr(diagonal, n)) for n in ("x1", "y1", "x2", "y2")] == [x0, y0, x0 + w, y0 - h]
        label = _attr(head, "data-capture-curve")
        for e in (e for e in evaluations if e["label"] == label):
            line = re.search(rf'<polyline class="series s\d" data-capture="{e["model_id"]}" points="([^"]+)"', body)
            first, *_, last = [tuple(map(float, p.split(","))) for p in line.group(1).split()]
            assert first == (x0, y0) and last == pytest.approx((x0 + w, y0 - h), abs=0.01)
            capacity = re.search(r'<line class="capacity"[^>]*>', body).group(0)
            assert float(_attr(capacity, "x1")) == pytest.approx(x0 + w * e["k_applied"] / e["n_clients"], abs=0.01)


def test_every_card_has_a_row_with_its_reason_in_spanish(sample, html):
    view = _view(html, "modelos")
    for card in sample["models"]["cards"]:
        row = re.search(rf'<tr data-card-row="{re.escape(card["file"])}">(.*?)</tr>', view, re.S).group(1)
        for reason in card["reasons"]:
            assert reason["message"] in row                  # original message, in the detail
        assert ("Ficha de demostración" in row) is card["demo"]
    demo = re.search(r'<tr data-card-row="delinquency_model_c.json">(.*?)</tr>', view, re.S).group(1)
    assert "partición no temporal" in demo and "<details" in demo


def test_the_technical_detail_has_every_metric_and_the_calibration(sample, html):
    view = _view(html, "modelos")
    detail = re.search(r'<details class="technical" id="models-technical">(.*?)</details>', view, re.S).group(1)
    for e in sample["models"]["evaluations"]:
        key = f'{e["label"]}.{e["model_id"]}'
        assert f'data-metrics="{key}"' in detail
        if e["status"] == "evaluated":
            assert format_ratio(e["metrics"]["brier"]) in detail
            assert len(re.findall(rf'data-calibration="{re.escape(key)}"', detail)) == len(e["metrics"]["calibration"])
        else:
            assert "scores incompletos" in detail
    for label in {e["label"] for e in sample["models"]["evaluations"] if e["status"] == "evaluated"}:
        assert f'data-metrics="{label}.random"' in detail


def test_slices_are_pending_and_scores_are_declared_simulated(html):
    view = _view(html, "modelos")
    assert 'id="slices-pending"' in view and "tenure_months" in view
    assert 'id="models-simulated"' in view


# --- management view (B12c) ------------------------------------------------------------------

def _management(data):
    return _view(render(data), "gestion")


def test_management_view_is_built(html):
    view = _view(html, "gestion")
    assert "Vista en construcción" not in view and 'id="management-cumulative"' in view


def test_cumulative_figures_come_from_the_json_with_their_trace(sample, html):
    view = _view(html, "gestion")
    cumulative = sample["management"]["cumulative"]
    for key in ("pv_cop_m", "ev_cop_m", "ac_cop_m", "eac_cop_m", "ceiling_cop_m"):
        assert format_cop_m(cumulative[key]) in view, key
    for key in ("spi", "cpi"):
        assert format_ratio(cumulative[key]) in view, key
    registered = [f["figure_id"] for f in sample["lineage"]["figures"] if f["figure_id"].startswith("management.")]
    assert registered
    for figure_id in registered:
        assert f'data-figure-id="{figure_id}"' in view and f'data-trace="{figure_id}"' in view


def _eac_line(view):
    return re.search(r'<p id="eac-ceiling">(.*?)</p>', view, re.S).group(1)


@pytest.mark.parametrize("eac,over,cls,words", [(200.0, True, "bad", "supera el techo"),
                                                 (170.0, False, "ok", "dentro del techo"),
                                                 (None, None, "warn", "no se puede estimar")])
def test_eac_is_compared_with_the_ceiling(sample, eac, over, cls, words):
    data = copy.deepcopy(sample)
    cumulative = data["management"]["cumulative"]
    cumulative.update(eac_cop_m=eac, eac_over_ceiling=over,
                      eac_minus_ceiling_cop_m=None if eac is None else eac - cumulative["ceiling_cop_m"])
    line = _eac_line(_management(data))
    assert f'class="status {cls}"' in line and words in line
    if eac is not None:
        assert format_cop_m(abs(eac - cumulative["ceiling_cop_m"])) in line


def test_baseline_shows_bac_reserve_change_requests_and_rate(sample, html):
    view = _view(html, "gestion")
    baseline = sample["management"]["baseline"]
    for key in ("ceiling_cop_m", "contingency_cop_m", "bac_cop_m", "reserve_remaining_cop_m", "logged_hour_cop_m"):
        assert format_cop_m(baseline[key]) in view, key
    for cr in baseline["change_requests"]:
        assert f'data-change-request="{cr["id"]}"' in view and format_cop_m(cr["approved_cop_m"]) in view
    assert f'COP {format_count(baseline["rate_cop"])}' in view and format_ratio(baseline["k_scale"]) in view


def _sprint_row(view, sprint):
    return re.search(rf'<tr data-sprint="{sprint}">(.*?)</tr>', view, re.S).group(1)


def test_one_row_per_sprint_with_reconstructed_hours_marked(sample):
    data = copy.deepcopy(sample)
    data["management"]["sprints"][1]["hours_estimated"] = False
    view = _management(data)
    for s in data["management"]["sprints"]:
        row = _sprint_row(view, s["sprint"])
        assert format_cop_m(s["ev_cop_m"]) in row and format_cop_m(s["ac_cop_m"]) in row
        assert ("reconstruidas" in row) is s["hours_estimated"]


def test_an_open_sprint_is_explained_only_while_open(sample):
    data = copy.deepcopy(sample)
    data["management"]["sprints"][-1]["done_sp"] = data["management"]["sprints"][-1]["committed_sp"] - 5
    note = re.search(r'<p class="note" id="open-sprint">(.*?)</p>', _management(data), re.S)
    assert note and "DoD" in note.group(1)
    for s in data["management"]["sprints"]:
        s["done_sp"] = s["committed_sp"]
    assert 'id="open-sprint"' not in _management(data)


def test_velocity_has_one_row_per_sprint(sample, html):
    view = _view(html, "gestion")
    for v in sample["management"]["velocity"]:
        assert f'data-velocity="{v["sprint"]}"' in view


def test_hours_outside_reported_sprints_are_flagged(sample, html):
    assert 'id="hours-outside"' not in _view(html, "gestion")
    data = copy.deepcopy(sample)
    data["management"]["hours_outside_reported_sprints"] = {"4": 6.5}
    assert 'id="hours-outside"' in _management(data)


@pytest.mark.parametrize("count,words", [(0, "Sin revisiones registradas"), (2, "2 revisiones registradas")])
def test_every_risk_is_listed_with_the_review_count(sample, count, words):
    data = copy.deepcopy(sample)
    data["management"]["risk_reviews_count"] = count
    view = _management(data)
    for r in data["management"]["risks"]:
        assert f'data-risk="{r["risk_id"]}"' in view
    assert words in re.search(r'<p[^>]*id="risk-reviews">(.*?)</p>', view, re.S).group(1)


def test_management_that_did_not_run_shows_only_its_reason(sample):
    data = copy.deepcopy(sample)
    data["management"] = {"status": "NOT_RUN", "reason": "hours_log failed Gate 1"}
    view = _management(data)
    assert 'id="management-not-run"' in view and "hours_log failed Gate 1" in view
    assert "data-sprint=" not in view and 'id="management-cumulative"' not in view   # only the hours log gate


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
