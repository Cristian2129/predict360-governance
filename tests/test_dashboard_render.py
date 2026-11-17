"""Tests for the static dashboard renderer (technical spec, section 11; US-10).

One self-contained index.html, rendered in Python from dashboard_data.json: it opens with a
double click, without network, and from GitHub Pages. Visual checks (projector and phone)
are manual and live in the PR checklist.
"""
import copy
import json
from datetime import date
from html import escape
import os
import re
import subprocess
import sys

import pytest

from src.predict360.config import ROOT
from src.predict360.dashboard_contract import SAMPLE_PATH
from src.predict360.formatting import format_ratio
from src.predict360.dashboard_render import (
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
    view = _view(html, "trazabilidad")
    assert "Vista en construcción" not in view
    for figure in sample["lineage"]["figures"]:
        assert figure["figure_id"] in view
    detail = view[view.index('id="trace-technical"'):]
    for entry in sample["lineage"]["manifest"]["sources"] + sample["lineage"]["manifest"]["outputs"]:
        assert entry["file"] in detail and entry["sha256"] in detail          # full hashes in the detail


def test_lineage_view_says_the_manifest_is_a_snapshot(html):
    assert ("Foto del manifiesto al exportar; el manifiesto final registra también este archivo y el tablero."
            in _view(html, "trazabilidad"))


@pytest.mark.parametrize("status,cls,words", [
    ("OK", "ok", "está íntegra"),
    ("TAMPERED", "bad", "fue alterado"),
    ("NOT_CHECKED", "warn", "no se verificó"),
])
def test_the_log_status_is_a_strip_in_plain_words(sample, status, cls, words):
    data = copy.deepcopy(sample)
    data["lineage"]["log_status"] = status
    strip = re.search(r'<div class="strip (\w+)" id="log-status"[^>]*>(.*?)</div>', render(data), re.S)
    assert strip and strip.group(1) == cls and words in strip.group(2)
    assert status not in _visible(strip.group(2))                           # the code stays in the detail


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


def test_the_views_of_the_spec_exist(html):
    assert [tab_id for tab_id, _ in TABS] == ["resumen", "datos", "trazabilidad", "modelos", "estres", "gestion"]
    ids = _ids(html)
    for tab_id, _ in TABS:
        assert tab_id in ids and f'href="#{tab_id}"' in html


def test_there_is_no_guided_mode_nor_handover_tab(html):
    # the story is told in the presentation; the dashboard only answers questions
    assert "guia-" not in html and "Presentar" not in html and "modo guiado" not in html.lower()
    assert 'id="entrega"' not in html and 'href="#entrega"' not in html
    assert "Vista en construcción" not in html
    from src.predict360 import dashboard_render
    assert not hasattr(dashboard_render, "GUIDED_STEPS")


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


# --- redesign (B12e-1): shell, header and summary ------------------------------------------------

def _without_details(fragment):
    """The fragment with every <details> (and what it holds, nested ones included) removed."""
    out, depth, i = [], 0, 0
    for match in re.finditer(r"<details\b|</details>", fragment):
        if depth == 0:
            out.append(fragment[i:match.start()])
        depth += 1 if match.group(0) == "<details" else -1
        i = match.end()
    if depth == 0:
        out.append(fragment[i:])
    return "".join(out)


def _visible(fragment):
    """Text a reader sees without opening any detail: no tags, no attributes, no <style>."""
    fragment = re.sub(r"<style>.*?</style>", "", _without_details(fragment), flags=re.S)
    return re.sub(r"<[^>]+>", " ", fragment)


def _header(html):
    return re.search(r'<header class="top">(.*?)</header>', html, re.S).group(1)


def test_the_sidebar_links_every_view_with_an_inline_icon(html):
    side = re.search(r'<aside class="side"[^>]*>(.*?)</aside>', html, re.S).group(1)
    for tab_id, label in TABS:
        link = re.search(rf'<a class="nav" href="#{tab_id}">(.*?)</a>', side, re.S)
        assert link, tab_id
        assert '<svg class="ico"' in link.group(1) and label in link.group(1)
    assert 'class="present"' not in side


def test_the_active_view_is_highlighted_without_javascript(html):
    for tab_id, _ in TABS:
        assert f'.app:has(#{tab_id}:target) .nav[href="#{tab_id}"]' in html
    assert '.app:not(:has(section.view:target)) .nav[href="#resumen"]' in html


def test_one_discreet_synthetic_label_in_the_header(html):
    header = _header(html)
    label = re.search(r'<span class="tag" id="banner-synthetic">(.*?)</span>\s*</div>', header, re.S)
    assert label and "Datos sintéticos" in label.group(1) and 'id="banner-simulated"' in label.group(1)
    assert 'class="banner' not in header                                    # no full-width strip for the demo


def test_real_data_keeps_a_loud_banner(sample):
    data = copy.deepcopy(sample)
    data["meta"].update(synthetic=False, scores_simulated=False)
    page = render(data)
    assert re.search(r'<div class="banner bad" id="banner-real"', page) and 'id="banner-synthetic"' not in page


@pytest.mark.parametrize("commit,words", [
    ("a" * 40 + "-dirty", "cambios sin commit"), ("unknown", "No se pudo identificar el commit"),
])
def test_the_commit_warning_is_in_the_header(sample, commit, words):
    data = copy.deepcopy(sample)
    data["meta"]["commit"] = commit
    warning = re.search(r'<span class="pill warn" id="banner-commit"[^>]*>(.*?)</span>\s*</span>',
                        _header(render(data)), re.S)
    assert warning and words in warning.group(1)


def _summary(data):
    return _view(render(data), "resumen")


def _answer(view):
    return re.search(r'<p class="answer" id="summary-answer">(.*?)</p>', view, re.S).group(1)


def test_the_summary_answers_its_question_from_the_json(sample, html):
    view = _view(html, "resumen")
    assert "¿Cuánto está en riesgo y podemos confiar en la respuesta?" in view
    total = sum(t["actual_cop_m"] for t in sample["exposure"]["tables"].values())
    answer = _answer(view)
    assert f"FinBank tiene {format_cop_m(total)} expuestos" in answer
    assert "cuadran con las del banco" in answer
    assert "ningún modelo tiene todavía evidencia suficiente" in answer


def test_the_answer_says_when_a_figure_does_not_reconcile(sample):
    data = copy.deepcopy(sample)
    data["exposure"]["tables"]["churn"].update(status="FAIL", difference_cop_m=5.0)
    answer = _answer(_summary(data))
    assert "no cuadran" in answer and "Fuga de clientes preferenciales" in answer


def test_the_answer_names_an_authorized_model_in_plain_words(sample):
    answer = _answer(_summary(_authorized(sample)))
    decision = _authorized(sample)["models"]["decisions"][0]
    target = {"delinquency": "Mora temprana", "churn": "Fuga de clientes preferenciales"}[decision["target"]]
    assert f"{target} tiene un modelo autorizado a despliegue en sombra (Modelo A)" in answer
    assert "producción" not in answer.lower()


def _kpis(view):
    return dict(re.findall(r'<article class="kpi" data-kpi="([^"]+)">(.*?)</article>', view, re.S))


def test_three_kpi_cards_exposure_and_verdict(sample, html):
    kpis = _kpis(_view(html, "resumen"))
    assert list(kpis) == ["delinquency", "churn", "verdict"]
    for table in ("delinquency", "churn"):
        rec = sample["exposure"]["tables"][table]
        assert format_cop_m(rec["actual_cop_m"]) in kpis[table]
        assert f'data-figure-id="exposure.{table}.observed_cop_m"' in kpis[table]
        assert 'class="pill ok"' in kpis[table] and "Cuadra con la cifra del banco" in kpis[table]
    assert "No autorizado" in kpis["verdict"] and "Evidencia insuficiente" in kpis["verdict"]


def test_a_kpi_that_does_not_reconcile_says_by_how_much(sample):
    data = copy.deepcopy(sample)
    data["exposure"]["tables"]["churn"].update(status="FAIL", difference_cop_m=5.0)
    churn = _kpis(_summary(data))["churn"]
    assert 'class="pill bad"' in churn and f"No cuadra: difiere en {format_cop_m(5.0)}" in churn


def test_an_authorized_verdict_kpi_says_shadow_deployment(sample):
    verdict = _kpis(_summary(_authorized(sample)))["verdict"]
    assert "Autorizado a despliegue en sombra" in verdict and 'class="pill ok"' in verdict


def _controls(view):
    parts = re.split(r'<div class="control" data-gate="(gate\d)">', view)
    return {gate: body.split('<div class="control"')[0] for gate, body in zip(parts[1::2], parts[2::2])}


def test_the_controls_row_says_each_gate_in_plain_words(sample, html):
    controls = _controls(_view(html, "resumen"))
    assert list(controls) == ["gate1", "gate2", "gate3"]
    assert 'class="pill warn"' in controls["gate1"] and "Pasan con 1 excepción aprobada" in controls["gate1"]
    counts = sample["models"]["cards"]
    admitted = sum(c["decision"] == "ADMITTED" for c in counts)
    assert f"{admitted} admitidas · 1 rechazada" in controls["gate2"]
    assert 'class="pill warn"' in controls["gate3"] and "No se verificó en esta corrida" in controls["gate3"]


@pytest.mark.parametrize("status,mismatches,cls,words", [
    ("PASS", [], "ok", "6 cifras verificadas · 0 diferencias"),
    ("FAIL", [{"figure_id": "x.y", "source": "output_file", "reason": "value_differs", "where": "evaluation.json",
               "expected": 1.0, "found": 2.0}], "bad", "1 diferencia"),
])
def test_the_consistency_control_follows_gate3(sample, status, mismatches, cls, words):
    data = copy.deepcopy(sample)
    data["gates"]["gate3"].update(status=status, checked=6, figures_checked=6, citations_checked=0,
                                  mismatches=mismatches)
    gate3 = _controls(_summary(data))["gate3"]
    assert f'class="pill {cls}"' in gate3 and words in gate3


def test_the_data_control_matches_the_data_view(sample):
    data = copy.deepcopy(sample)
    data["gates"]["gate1"]["tables"]["churn"].update(status="PASS", failed_rules=[])
    data["gates"]["gate1"]["tables"]["hours_log"].update(status="FAIL")   # PCM's own log: shown in Gestión
    gate1 = _controls(_summary(data))["gate1"]
    assert 'class="pill ok"' in gate1 and "Cumplen sus contratos" in gate1


def test_one_dictionary_names_every_model_label_and_target_in_plain_spanish(sample):
    from src.predict360 import dashboard_render
    names = dashboard_render.PLAIN_NAMES
    models = sample["models"]
    ids = ({e["model_id"] for e in models["evaluations"]} | {e["label"] for e in models["evaluations"]}
           | {e["target"] for e in models["evaluations"]} | {c["model_id"] for c in models["cards"]})
    assert ids <= set(names)
    assert names["baseline_rule"] == "Regla actual" and names["model_a"] == "Modelo A"
    assert names["delinquency_30"] == "Mora a 30 días" and names["delinquency"] == "Mora temprana"
    for old in ("TARGET_NAMES", "LABEL_NAMES", "COLUMN_NAMES"):
        assert not hasattr(dashboard_render, old), old


def test_the_summary_shows_no_technical_ids_outside_its_detail(sample, html):
    view = _view(html, "resumen")
    assert '<details class="technical" id="summary-technical">' in view
    text = _visible(view)
    tokens = ({e["model_id"] for e in sample["models"]["evaluations"]} | {e["label"] for e in sample["models"]["evaluations"]}
              | {"delinquency", "churn", "PASS", "FAIL", "gate1", "gate2", "gate3", "temporal_split", "W-01"})
    for token in tokens:
        assert token not in text, token
    assert not re.search(r"\b[a-z]+_[a-z0-9_]+\b", text)                    # no snake_case identifiers


def test_the_summary_detail_keeps_run_reconciliation_and_reasons(sample, html):
    view = _view(html, "resumen")
    detail = view[view.index('id="summary-technical"'):]
    meta = sample["meta"]
    for value in (meta["run_id"], meta["config"], meta["snapshot_date"], meta["commit"]):
        assert value in detail
    for rec in sample["exposure"]["tables"].values():
        for key in ("expected_cop_m", "difference_cop_m", "tolerance_cop_m"):
            assert format_cop_m(rec[key]) in detail
    for decision in sample["models"]["decisions"]:
        assert f'data-decision="{decision["target"]}"' in detail
        assert escape(decision["reason"]) in detail
    assert 'data-demo-card="' in detail and 'data-trace="exposure.delinquency.observed_cop_m"' in detail


def test_the_summary_says_exposure_is_not_loss(html):
    assert "Son exposición en riesgo, no pérdida." in _visible(_view(html, "resumen"))


# --- data view (B12e-4): can the data of this run be trusted? -----------------------------------

DATA_TABLES = ("delinquency", "churn", "scores")


def _data(data):
    return _view(render(data), "datos")


def _data_answer(view):
    return re.search(r'<p class="answer" id="data-answer">(.*?)</p>', view, re.S).group(1)


def test_the_data_view_answers_its_question(sample, html):
    view = _view(html, "datos")
    assert "¿Se puede confiar en los datos?" in view
    waiver = sample["quality"]["waivers"][0]
    pct = sample["quality"]["missing"][waiver["table"]][waiver["column"]]["pct"]
    answer = _data_answer(view)
    assert answer.startswith("Sí, con 1 excepción aprobada")
    assert format_pct(pct / 100) in answer and "antigüedad" in answer and waiver["expires"] in answer


@pytest.mark.parametrize("status,start", [("PASS", "Sí: las 3 tablas"), ("FAIL", "No:")])
def test_the_data_answer_follows_gate1(sample, status, start):
    data = copy.deepcopy(sample)
    tables = data["gates"]["gate1"]["tables"]
    tables["churn"].update(status="PASS", failed_rules=[])
    if status == "FAIL":
        tables["scores"].update(status="FAIL", failed_rules=[{"rule": "expect_column_values_to_be_between",
                                "column": "score", "critical": True, "unexpected_count": 2, "unexpected_pct": 0.1,
                                "waived_by": None}])
        data["gates"]["gate1"]["status"] = "FAIL"
    assert _data_answer(_data(data)).startswith(start)


def _table_cards(view):
    return dict(re.findall(r'<article class="kpi" data-table="([^"]+)">(.*?)</article>', view, re.S))


def test_one_card_per_data_table_with_its_size_and_state(sample, html):
    cards = _table_cards(_view(html, "datos"))
    assert list(cards) == list(DATA_TABLES)
    funnel = sample["quality"]["labeling_funnel"]
    for table in ("delinquency", "churn"):
        assert f'{format_count(funnel[table]["steps"][0]["clients"])} clientes' in cards[table]
    assert f'{format_count(sample["gates"]["gate1"]["tables"]["scores"]["rows"])} filas' in cards["scores"]
    assert 'class="pill ok"' in cards["delinquency"] and 'class="pill warn"' in cards["churn"]
    assert "Pasa con una excepción aprobada" in cards["churn"]


def test_gate1_lists_the_data_tables_but_not_the_hours_log(sample, html):
    view = _view(html, "datos")
    detail = view[view.index('id="data-technical"'):]
    for table in DATA_TABLES:
        assert f'data-gate1-table="{table}"' in detail
    assert 'data-gate1-table="hours_log"' not in view
    rule = sample["gates"]["gate1"]["tables"]["churn"]["failed_rules"][0]
    row = re.search(r'<tr data-gate1-table="churn">(.*?)</tr>', detail, re.S).group(1)
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


def test_one_bar_per_limited_column_with_missing_values_against_its_limit(sample, html):
    view = _view(html, "datos")
    missing = sample["quality"]["missing"]
    expected = {f"{t}.{c}" for t in DATA_TABLES for c, m in missing[t].items()
                if m["limit_pct"] is not None and m["count"] > 0}
    svgs = re.findall(r'<svg class="hbar" data-missing="([^"]+)"[^>]*>(.*?)</svg>', view, re.S)
    assert {key for key, _ in svgs} == expected
    for key, body in svgs:
        head = re.search(rf'<svg class="hbar" data-missing="{re.escape(key)}"[^>]*>', view).group(0)
        x0, w, vmax = (float(_attr(head, n)) for n in ("data-x0", "data-w", "data-max"))
        table, column = key.split(".")
        m = missing[table][column]
        bar = re.search(r'<rect class="value"[^>]*>', body).group(0)
        limit = re.search(r'<line class="limit"[^>]*>', body).group(0)
        assert float(_attr(bar, "width")) == pytest.approx(w * m["pct"] / vmax, abs=0.01)
        assert float(_attr(limit, "x1")) == pytest.approx(x0 + w * m["limit_pct"] / vmax, abs=0.01)
        assert format_pct(m["pct"] / 100) in body and format_pct(m["limit_pct"] / 100) in body
    assert "first_delinquency_date" not in _visible(view) and "cancellation_date" not in _visible(view)


def test_every_limited_column_stays_in_the_detail(sample, html):
    view = _view(html, "datos")
    detail = re.search(r'<details class="technical" id="data-technical">(.*)', view, re.S).group(1)
    every = dict(re.findall(r'<tr data-missing-all="([^"]+)">(.*?)</tr>', detail, re.S))
    limited = {f"{t}.{c}" for t in DATA_TABLES for c, m in sample["quality"]["missing"][t].items()
               if m["limit_pct"] is not None}
    assert set(every) == limited and 'class="status ok"' in every["delinquency.client_id"]
    assert "W-01" in every["churn.tenure_months"]


def test_a_column_over_its_limit_without_a_waiver_is_red(sample):
    data = copy.deepcopy(sample)
    data["quality"]["missing"]["delinquency"]["tenure_months"].update(count=50, pct=10.0)
    assert '<svg class="hbar" data-missing="delinquency.tenure_months" data-state="bad"' in _data(data)


def test_without_missing_values_the_view_says_so(sample):
    data = copy.deepcopy(sample)
    for columns in data["quality"]["missing"].values():
        for m in columns.values():
            m.update(count=0, pct=0.0)
    view = _data(data)
    assert '<svg class="hbar"' not in view and 'id="missing-none"' in view


def test_the_waiver_card_is_in_spanish_with_a_time_bar(sample, html):
    view = _view(html, "datos")
    waiver = sample["quality"]["waivers"][0]
    card = re.search(rf'<div class="card" data-waiver="{waiver["id"]}">(.*?)<details', view, re.S).group(1)
    pct = sample["quality"]["missing"][waiver["table"]][waiver["column"]]["pct"]
    plain = re.search(r'<p class="plain">(.*?)</p>', card, re.S).group(1)
    assert f"El {format_pct(pct / 100)}" in plain and "antigüedad" in plain and "no se rellena, se evalúa aparte" in plain
    assert waiver["expires"] in card and waiver["approved_by"] in card and waiver["risk"] in card
    assert waiver["reason"] not in card                                     # English text: in its detail
    run_day = date.fromisoformat(sample["meta"]["generated_at"][:10])
    start, end = date.fromisoformat(waiver["date"]), date.fromisoformat(waiver["expires"])
    elapsed = 100 * min(max((run_day - start).days / (end - start).days, 0), 1)
    bar = re.search(rf'<div class="timeline" data-waiver-timeline="{waiver["id"]}">.*?style="width: ([\d.]+)%"',
                    card, re.S)
    assert bar and float(bar.group(1)) == pytest.approx(elapsed, abs=0.05)


@pytest.mark.parametrize("generated_at,soon", [("2026-11-14T08:00:00Z", True), ("2026-09-01T08:00:00Z", False)])
def test_a_waiver_close_to_expiry_is_flagged(sample, generated_at, soon):
    data = copy.deepcopy(sample)
    data["meta"]["generated_at"] = generated_at
    assert ('data-waiver-expiring="W-01"' in _data(data)) is soon


def test_one_stacked_bar_per_horizon_that_adds_up_to_every_client(sample, html):
    view = _view(html, "datos")
    for target, funnel in sample["quality"]["labeling_funnel"].items():
        total = funnel["steps"][0]["clients"]
        for label, h in funnel["horizons"].items():
            bar = re.search(rf'<div class="stacked" data-horizon-bar="{label}"[^>]*>(.*?)</div>', view, re.S).group(1)
            widths = {k: float(v) for k, v in
                      re.findall(r'data-segment="(\w+)"[^>]*style="width: ([\d.]+)%"', bar)}
            assert widths["no_event"] == pytest.approx(100 * (h["mature_clients"] - h["positive_clients"]) / total, abs=0.01)
            assert widths["event"] == pytest.approx(100 * h["positive_clients"] / total, abs=0.01)
            assert widths["immature"] == pytest.approx(100 * (total - h["mature_clients"]) / total, abs=0.01)


def test_each_horizon_is_explained_in_plain_words(sample, html):
    view = _view(html, "datos")
    for target, funnel in sample["quality"]["labeling_funnel"].items():
        total = funnel["steps"][0]["clients"]
        for label, h in funnel["horizons"].items():
            plain = re.search(rf'<p class="plain" data-horizon="{label}">(.*?)</p>', view, re.S).group(1)
            assert f"De {format_count(total)} clientes, {format_count(h['mature_clients'])}" in plain
            assert format_count(total - h["mature_clients"]) in plain and "aún no se sabe" in plain
            assert format_pct(h["base_rate"]) in plain


def test_the_funnel_steps_and_unverifiable_ones_are_in_the_detail(sample, html):
    view = _view(html, "datos")
    detail = view[view.index('id="data-technical"'):]
    for target, funnel in sample["quality"]["labeling_funnel"].items():
        for step in funnel["steps"]:
            row = re.search(rf'<tr data-step="{step["step"]}">(.*?)</tr>', detail, re.S).group(1)
            if step.get("status") == "not_verifiable":
                assert step["missing_column"] in row and f"{target}_v2" in row and "No verificable" in row
                assert f'data-not-verifiable="{target}"' in view               # said in the view, detail below


def test_every_data_chart_says_how_to_read_it(html):
    view = _view(html, "datos")
    charts = len(re.findall(r'<svg class="hbar"', view)) + len(re.findall(r'data-funnel="', view))
    assert charts and len(re.findall(r'<details class="how"><summary>¿Cómo se lee\?</summary>', view)) >= charts


def test_the_data_view_shows_no_technical_ids_outside_its_detail(sample, html):
    text = _visible(_view(html, "datos"))
    for token in ("delinquency", "churn_3m", "PASS", "FAIL", "tenure_months", "expect_", "not_verifiable"):
        assert token not in text, token
    assert not re.search(r"\b[a-z]+_[a-z0-9_]+\b", text)


# --- traceability view (B12e-4): where does every figure come from? ------------------------------

def _trace_view(data):
    return _view(render(data), "trazabilidad")


def test_the_traceability_view_answers_its_question(sample, html):
    view = _view(html, "trazabilidad")
    assert "¿De dónde sale cada cifra?" in view
    manifest = sample["lineage"]["manifest"]
    answer = re.search(r'<p class="answer" id="trace-answer">(.*?)</p>', view, re.S).group(1)
    assert f'{format_count(len(sample["lineage"]["figures"]))} cifras' in answer
    assert f'{format_count(len(manifest["sources"]))} fuentes' in answer


def test_the_flow_counts_sources_controls_outputs_and_figures(sample, html):
    view = _view(html, "trazabilidad")
    manifest = sample["lineage"]["manifest"]
    steps = dict(re.findall(r'<li data-flow="(\w+)">.*?<strong>([^<]+)</strong>', view, re.S))
    assert steps == {"sources": format_count(len(manifest["sources"])), "controls": "3",
                     "outputs": format_count(len(manifest["outputs"])),
                     "figures": format_count(len(sample["lineage"]["figures"]))}


def _story(view):
    return dict(re.findall(r'<li data-trace-step="(\w+)">(.*?)</li>', view, re.S))


def test_the_delinquency_exposure_is_traced_in_five_steps(sample, html):
    view = _view(html, "trazabilidad")
    figure = _registered(sample)["exposure.delinquency.observed_cop_m"]
    manifest = sample["lineage"]["manifest"]
    source = next(s for s in manifest["sources"] if s["name"] == "delinquency")
    output = next(o for o in manifest["outputs"] if o["file"] == figure["file"])
    story = _story(view)
    assert list(story) == ["file", "script", "output", "commit", "check"]
    assert source["file"] in story["file"] and source["sha256"][:8] in story["file"]
    assert source["sha256"] not in story["file"]                               # 8 characters in the view
    assert figure["script"] in story["script"]
    assert figure["file"] in story["output"] and output["sha256"][:8] in story["output"]
    assert sample["meta"]["commit"][:8] in story["commit"]
    assert format_cop_m(figure["value"]) in view[view.index('id="trace-story"'):]


@pytest.mark.parametrize("status,mismatch,cls", [("PASS", False, "ok"), ("FAIL", True, "bad"), ("NOT_RUN", False, "warn")])
def test_the_last_step_says_whether_gate3_checked_the_figure(sample, status, mismatch, cls):
    data = copy.deepcopy(sample)
    mismatches = [{"figure_id": "exposure.delinquency.observed_cop_m", "source": "output_file", "where": "x",
                   "expected": 1.0, "found": 2.0, "reason": "value_differs"}] if mismatch else []
    data["gates"]["gate3"].update(status=status, mismatches=mismatches)
    assert f'class="pill {cls}"' in _story(_trace_view(data))["check"]


def test_the_finder_lists_every_figure_grouped_by_objective(sample, html):
    view = _view(html, "trazabilidad")
    finder = re.search(r'<details class="finder" id="figure-finder">(.*?)</details>', view, re.S).group(1)
    assert "Buscar una cifra" in finder
    rows = dict(re.findall(r'<tr data-figure-row="([^"]+)">(.*?)</tr>', finder, re.S))
    assert set(rows) == {f["figure_id"] for f in sample["lineage"]["figures"]}
    outputs = {o["file"]: o["sha256"] for o in sample["lineage"]["manifest"]["outputs"]}
    for f in sample["lineage"]["figures"]:
        row = rows[f["figure_id"]]
        name = re.search(r'<span class="name">(.*?)</span>\s*<code class="id">(.*?)</code>', row)
        assert name and name.group(2) == f["figure_id"] and "_" not in name.group(1)   # plain name first
        assert outputs[f["file"]][:8] in row and outputs[f["file"]] not in row
        assert 'class="num"' in row
    captions = re.findall(r"<caption>(.*?)</caption>", finder)
    assert "Mora temprana" in captions and "Gestión del proyecto" in captions


def test_the_traceability_view_shows_no_technical_ids_outside_its_detail(html):
    view = _view(html, "trazabilidad")
    text = _visible(re.sub(r'<code[^>]*>.*?</code>', "", view, flags=re.S))   # paths and ids are shown as code
    for token in ("OK", "TAMPERED", "sha256", "delinquency", "figure_id"):
        assert not re.search(rf"\b{token}\b", text), token


# --- models view (B12e-5): which model ranks best, and is the evidence enough? ----------------

MODELS_QUESTION = "¿Qué modelo ordena mejor y alcanza la evidencia?"


def _models(data):
    return _view(render(data), "modelos")


def _attr(tag, name):
    return re.search(rf'\b{name}="([^"]*)"', tag).group(1)


def _compared(data):
    return [e for e in data["models"]["evaluations"] if e["status"] == "evaluated" and e["vs_baseline"]]


def _models_answer(view):
    return re.search(r'<p class="answer" id="models-answer">(.*?)</p>', view, re.S).group(1)


def _authorized_delinquency(sample):
    data = copy.deepcopy(sample)
    decision = next(d for d in data["models"]["decisions"] if d["target"] == "delinquency")
    decision.update(verdict="authorized_for_shadow_deployment", reason_code="authorized", model_id="model_b")
    return data


def test_the_models_view_answers_its_question(sample, html):
    view = _view(html, "modelos")
    assert f'<p class="q">{MODELS_QUESTION}</p>' in view
    answer = _models_answer(view)
    assert answer.startswith("Ningún modelo")                       # the fixture authorizes nothing
    assert "Modelo B" in answer and "Mora a 60 días" in answer      # it beats the rule only at 60 days
    assert "producción" not in view.lower()


def test_an_authorized_model_is_named_in_the_answer(sample):
    answer = _models_answer(_models(_authorized_delinquency(sample)))
    assert "Modelo B" in answer and "despliegue en sombra" in answer
    assert "producción" not in answer.lower()


@pytest.mark.parametrize("code,tag", [("insufficient_evidence", "Evidencia insuficiente"),
                                      ("authorized", "Supera la regla"),
                                      ("does_not_beat_baseline", "No supera la regla")])
def test_one_verdict_card_per_target_tagged_by_the_reason_of_its_decision(sample, code, tag):
    data = copy.deepcopy(sample)
    decision = next(d for d in data["models"]["decisions"] if d["target"] == "delinquency")
    decision["reason_code"] = code
    if code == "authorized":
        decision.update(verdict="authorized_for_shadow_deployment", model_id="model_a")
    view = _models(data)
    verdict = view[view.index('id="models-verdict"'):view.index('id="models-intervals"')]
    for d in data["models"]["decisions"]:
        assert f'data-verdict="{d["target"]}"' in verdict
    assert re.search(rf'<span class="pill \w+" data-decision-tag="delinquency">.*?<span>{tag}</span>', verdict, re.S)


# intervals: one panel per target, its own scale, round ticks, both sides labelled

def _ci_svgs(view):
    return re.findall(r'(<svg class="ci"[^>]*>)(.*?)</svg>', view, re.S)


def test_one_interval_panel_per_compared_target_with_its_own_scale(sample, html):
    svgs = _ci_svgs(_view(html, "modelos"))
    assert sorted(_attr(head, "data-ci-target") for head, _ in svgs) == sorted({e["target"] for e in _compared(sample)})
    for head, _ in svgs:
        for name in ("data-vmin", "data-vmax", "data-x0", "data-xscale"):
            assert name in head


def test_the_drawn_interval_matches_the_evaluation(sample, html):
    expected = {f'{e["label"]}.{e["model_id"]}': e["vs_baseline"] for e in _compared(sample)}
    drawn = set()
    for head, body in _ci_svgs(_view(html, "modelos")):
        vmin, x0, scale = (float(_attr(head, n)) for n in ("data-vmin", "data-x0", "data-xscale"))
        px = lambda v: x0 + (v - vmin) * scale
        for key, body_row in re.findall(r'<g data-ci="([^"]+)"[^>]*>(.*?)</g>', body, re.S):
            drawn.add(key)
            vs = expected[key]
            line = re.search(r'<line class="ci-range"[^>]*>', body_row).group(0)
            dot = re.search(r'<circle class="ci-point"[^>]*>', body_row).group(0)
            assert float(_attr(line, "x1")) == pytest.approx(px(vs["ci_low_cop_m"]), abs=0.01)
            assert float(_attr(line, "x2")) == pytest.approx(px(vs["ci_high_cop_m"]), abs=0.01)
            assert float(_attr(dot, "cx")) == pytest.approx(px(vs["difference_cop_m"]), abs=0.01)
        zero = re.search(r'<line class="zero"[^>]*>', body).group(0)
        assert float(_attr(zero, "x1")) == pytest.approx(px(0.0), abs=0.01)
    assert drawn == set(expected)


def test_the_interval_axis_has_round_ticks_and_a_soft_grid(sample, html):
    for head, body in _ci_svgs(_view(html, "modelos")):
        target = _attr(head, "data-ci-target")
        rows = [e["vs_baseline"] for e in _compared(sample) if e["target"] == target]
        ticks = [float(v) for v in re.findall(r'<line class="grid" data-value="([^"]+)"', body)]
        assert 0.0 in ticks and len(ticks) >= 3
        step = ticks[1] - ticks[0]
        assert step in (10, 50, 100, 500, 1000, 5000)
        assert all(b - a == step for a, b in zip(ticks, ticks[1:])) and all(t % step == 0 for t in ticks)
        assert ticks[0] <= min(vs["ci_low_cop_m"] for vs in rows) and ticks[-1] >= max(vs["ci_high_cop_m"] for vs in rows)
        assert float(_attr(head, "data-vmin")) == ticks[0] and float(_attr(head, "data-vmax")) == ticks[-1]
        for t in ticks:                                                    # every gridline carries its label
            assert f'<text class="tick" data-tick-value="{t:g}"' in body


def test_both_sides_are_labelled_and_the_rule_side_is_shaded(html):
    for head, body in _ci_svgs(_view(html, "modelos")):
        vmin, x0, scale = (float(_attr(head, n)) for n in ("data-vmin", "data-x0", "data-xscale"))
        assert "← la regla actual es mejor" in body and "el modelo es mejor →" in body
        shade = re.search(r'<rect class="rule-better"[^>]*>', body).group(0)
        assert float(_attr(shade, "x")) == pytest.approx(x0, abs=0.01)
        assert float(_attr(shade, "x")) + float(_attr(shade, "width")) == pytest.approx(x0 - vmin * scale, abs=0.01)


def test_the_interval_is_green_only_when_it_clears_zero(sample, html):
    outcome_class = {"beats": "ok", "insufficient_evidence": "warn", "does_not_beat_baseline": "bad"}
    view = _view(html, "modelos")
    for e in _compared(sample):
        vs = e["vs_baseline"]
        key = f'{e["label"]}.{e["model_id"]}'
        cls = re.search(rf'<g data-ci="{re.escape(key)}" class="(\w+)"', view).group(1)
        assert cls == outcome_class[vs["outcome"]]
        assert (cls == "ok") == (vs["ci_low_cop_m"] > vs["margin_cop_m"])


def test_the_point_figure_is_written_over_each_point(sample, html):
    view = _view(html, "modelos")
    for e in _compared(sample):
        key = f'{e["label"]}.{e["model_id"]}'
        row = re.search(rf'<g data-ci="{re.escape(key)}"[^>]*>(.*?)</g>', view, re.S).group(1)
        value = re.search(r'<text class="ci-value"[^>]*>([^<]*)</text>', row).group(1)
        assert value == format_cop_m(e["vs_baseline"]["difference_cop_m"])
        assert f'{_plain_name(e["model_id"])} · {_plain_name(e["label"])}' in row


def _plain_name(key):
    from src.predict360.dashboard_render import PLAIN_NAMES
    return PLAIN_NAMES[key]


@pytest.mark.parametrize("level,words", [(0.9, "90 %"), (0.95, "95 %")])
def test_the_axis_title_takes_the_confidence_level_from_the_json(sample, level, words):
    data = copy.deepcopy(sample)
    for e in _compared(data):
        e["vs_baseline"]["confidence_level"] = level
    view = _models(data)
    assert f"Ventaja sobre la regla actual (COP millones), intervalo de confianza al {words}" in view


def test_delinquency_must_win_at_30_and_60_days(html):
    card = re.search(r'data-decision-card="delinquency">(.*?)</p>', _view(html, "modelos"), re.S).group(1)
    assert "30 y a 60 días" in card


def test_a_target_without_a_comparison_says_so(sample, html):
    card = re.search(r'data-decision-card="churn">(.*?)</div>', _view(html, "modelos"), re.S).group(1)
    assert 'id="ci-none-churn"' in card                     # fixture: churn baseline not evaluated
    assert "Regla actual" in card


# capture curve: quarter axes, a conclusion as title, series named on the chart, today marked

def _capture_svgs(view):
    return re.findall(r'(<svg class="capture"[^>]*>)(.*?)</svg>', view, re.S)


def _capture_figure(view, label):
    return re.search(rf'<figure data-capture-for="{label}">(.*?)</figure>', view, re.S).group(1)


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
            line = re.search(rf'<polyline class="series m-{e["model_id"]}" data-capture="{e["model_id"]}" '
                             r'points="([^"]+)"', body)
            first, *_, last = [tuple(map(float, p.split(","))) for p in line.group(1).split()]
            assert first == (x0, y0) and last == pytest.approx((x0 + w, y0 - h), abs=0.01)
            capacity = re.search(r'<line class="capacity"[^>]*>', body).group(0)
            assert float(_attr(capacity, "x1")) == pytest.approx(x0 + w * e["k_applied"] / e["n_clients"], abs=0.01)


def test_the_capture_axes_have_quarter_ticks_and_a_grid(html):
    for _, body in _capture_svgs(_view(html, "modelos")):
        for axis in ("x", "y"):
            values = re.findall(rf'<line class="grid" data-axis="{axis}" data-value="(\d+)"', body)
            assert values == ["0", "25", "50", "75", "100"], axis
        for value in (0, 25, 50, 75, 100):
            assert f">{value} %</text>" in body


def test_the_capture_title_is_a_conclusion_from_the_json(sample, html):
    view = _view(html, "modelos")
    for label, evaluations in _evaluated_by_label(sample).items():
        title = re.search(r'<h4 data-capture-title="[^"]+">(.*?)</h4>', _capture_figure(view, label), re.S).group(1)
        best = max(evaluations, key=lambda e: e["at_k"]["capture"])
        assert _plain_name(best["model_id"]) in title and format_pct(best["at_k"]["capture"]) in title
        assert f'llamando a {format_count(best["k_applied"])} clientes (capacidad de hoy)' in title


def test_each_series_is_named_on_the_chart_and_today_is_marked(sample, html):
    view = _view(html, "modelos")
    for label, evaluations in _evaluated_by_label(sample).items():
        figure = _capture_figure(view, label)
        for e in evaluations:
            name = re.search(rf'<text class="series-label m-{e["model_id"]}" data-series-label="{e["model_id"]}"'
                             r'[^>]*>([^<]*)</text>', figure)
            assert name and name.group(1) == _plain_name(e["model_id"])
        today = re.search(r'<text class="today"[^>]*>([^<]*)</text>', figure).group(1)
        assert today == f'Capacidad de hoy: {format_count(evaluations[0]["k_applied"])} clientes'
        assert ">Al azar</text>" in figure


def test_every_model_keeps_its_colour_in_every_chart(sample, html):
    for view_id, attribute in (("modelos", "data-capture"), ("estres", "data-series")):
        view = _view(html, view_id)
        for e in (e for e in sample["models"]["evaluations"] if e["status"] == "evaluated"):
            assert re.search(rf'class="series m-{e["model_id"]}" {attribute}="{e["model_id"]}"', view), (view_id, e["model_id"])
        assert not re.search(r'class="(series|kstar|swatch) s\d', view)              # never by position
    css = (ROOT / "src" / "predict360" / "dashboard_assets" / "styles.css").read_text(encoding="utf-8")
    for model_id in ("baseline_rule", "model_a", "model_b"):
        assert f".m-{model_id}" in css


# Gate 2 cards and the technical detail

def test_every_card_has_a_row_with_its_reason_in_spanish(sample, html):
    view = _view(html, "modelos")
    for card in sample["models"]["cards"]:
        row = re.search(rf'<tr data-card-row="{re.escape(card["file"])}">(.*?)</tr>', view, re.S).group(1)
        for reason in card["reasons"]:
            assert reason["message"] in row                  # original message, in the detail
        assert ("(demostración)" in row) is card["demo"]
    demo = re.search(r'<tr data-card-row="delinquency_model_c.json">(.*?)</tr>', view, re.S).group(1)
    assert "Modelo C (demostración)" in _visible(demo) and "partición no temporal" in demo and "<details" in demo


def _technical(view):
    start = view.index('<details class="technical" id="models-technical">')
    return view[start:]


def test_the_technical_detail_has_a_target_selector_and_four_questions(sample, html):
    detail = _technical(_view(html, "modelos"))
    labels = sorted({e["label"] for e in sample["models"]["evaluations"]})
    assert sorted(re.findall(r'<input type="radio" name="metrics-label" id="metrics-([^"]+)"', detail)) == labels
    for question in ("¿Encuentra la plata?", "¿Acierta?", "¿Son confiables sus probabilidades?", "¿Cuánto vale?"):
        assert re.search(rf'<th colspan="\d+" class="group">{re.escape(question)}</th>', detail), question


def test_the_technical_detail_has_every_metric_and_the_calibration(sample, html):
    detail = _technical(_view(html, "modelos"))
    for e in sample["models"]["evaluations"]:
        key = f'{e["label"]}.{e["model_id"]}'
        row = re.search(rf'<tr data-metrics="{re.escape(key)}">(.*?)</tr>', detail, re.S)
        assert row, key
        if e["status"] == "evaluated":
            assert format_ratio(e["metrics"]["brier"]) in row.group(1)
            assert format_pct(e["breakeven_effectiveness"]) in row.group(1)       # «¿Cuánto vale?»
            assert len(re.findall(rf'data-calibration="{re.escape(key)}"', detail)) == len(e["metrics"]["calibration"])
        else:
            assert "scores incompletos" in row.group(1)
    for label in {e["label"] for e in sample["models"]["evaluations"] if e["status"] == "evaluated"}:
        assert f'data-metrics="{label}.random"' in detail


def test_calibration_is_a_small_chart_per_model_with_the_deciles_folded(sample, html):
    detail = _technical(_view(html, "modelos"))
    for e in (e for e in sample["models"]["evaluations"] if e["status"] == "evaluated"):
        key = f'{e["label"]}.{e["model_id"]}'
        svg = re.search(rf'<svg class="calib" data-calibration-chart="{re.escape(key)}"[^>]*>(.*?)</svg>', detail, re.S)
        assert svg, key
        assert len(re.findall(r'<circle class="calib-point', svg.group(1))) == len(e["metrics"]["calibration"])
        assert '<line class="diagonal"' in svg.group(1)
    for table in re.findall(r'<table class="data"><caption>Calibración por decil[^<]*</caption>', detail):
        before = detail[:detail.index(table)]
        assert before.rfind("<details") > before.rfind("</details>")          # inside a fold of its own


def test_slices_are_pending_and_scores_are_declared_simulated(html):
    view = _view(html, "modelos")
    slices = re.search(r'<p class="pending" id="slices-pending">(.*?)</p>', view, re.S).group(1)
    assert "B8c" not in slices and "antigüedad" in slices
    assert 'id="models-simulated"' in view


def test_the_models_view_shows_no_technical_ids_outside_its_detail(sample, html):
    text = _visible(_view(html, "modelos"))
    models = sample["models"]
    tokens = ({e["model_id"] for e in models["evaluations"]} | {e["label"] for e in models["evaluations"]}
              | {c["model_id"] for c in models["cards"]} | {"delinquency", "churn", "temporal_split", "tenure_months"})
    for token in tokens:
        assert not re.search(rf"\b{token}\b", text), token
    assert not re.search(r"\b[a-z]+_[a-z0-9_]+\b", text)


def test_the_models_charts_use_the_full_width():
    css = (ROOT / "src" / "predict360" / "dashboard_assets" / "styles.css").read_text(encoding="utf-8")
    assert not re.search(r"svg\.(ci|capture)\s*\{[^}]*max-width", css)


# What K means: defined once per target (Models) and per label (Stress), from k_applied

def _k_by_label(data):
    return {label: rows[0]["k_applied"] for label, rows in _evaluated_by_label(data).items()}


def _k_definitions(view):
    return re.findall(r'<p class="k-def" data-k-definition="([^"]+)">(.*?)</p>', view, re.S)


def test_every_target_defines_k_with_the_k_of_each_of_its_labels(sample, html):
    view = _view(html, "modelos")
    ks = _k_by_label(sample)
    targets = {}
    for e in sample["models"]["evaluations"]:
        if e["status"] == "evaluated":
            targets.setdefault(e["target"], set()).add(e["label"])
    definitions = dict(_k_definitions(view))
    assert set(definitions) == set(targets)
    values = {k: v for item in sample["assumptions"] for k, v in item["value"].items()}
    for target, labels in targets.items():
        text = definitions[target]
        assert "¿Qué es K?" in text and "K*" in text and "mejor número de contactos" in text
        share = values["value.default_capacity_share"]
        assert f'el {format_pct(share, decimals=0)} de los clientes evaluados (supuesto de diseño)' in text
        assert format_pct(share) not in text                       # «10 %», not «10,0 %»
        drawn = dict(re.findall(r'<span data-k="([^"]+)">([^<]+)</span>', text))
        assert drawn == {label: format_count(ks[label]) for label in labels}
        for label in labels:
            assert _plain_name(label) in text


def test_every_stress_card_defines_k_with_its_own_k(sample, html):
    view = _view(html, "estres")
    ks = _k_by_label(sample)
    definitions = dict(_k_definitions(view))
    assert set(definitions) == set(ks)
    for label, text in definitions.items():
        assert "¿Qué es K?" in text and "mejor número de contactos" in text
        assert dict(re.findall(r'<span data-k="([^"]+)">([^<]+)</span>', text)) == {label: format_count(ks[label])}


def _main_text(view):
    """What a reader sees outside the K definitions and the technical detail."""
    view = re.sub(r"<script.*?</script>", "", view, flags=re.S)
    return _visible(re.sub(r'<p class="k-def".*?</p>', "", view, flags=re.S))


@pytest.mark.parametrize("view_id", ["modelos", "estres"])
def test_the_letter_k_appears_only_in_its_definition_and_the_technical_detail(html, view_id):
    view = _view(html, view_id)
    assert not re.search(r"\bK\b|K\*", _main_text(view)), view_id
    for legend in re.findall(r'<ul class="legend">(.*?)</ul>', view, re.S):
        assert not re.search(r"\bK\b|K\*", legend)
    if view_id == "estres":
        assert "Mejor número de contactos" in view


@pytest.mark.parametrize("view_id", ["modelos", "estres"])
def test_no_main_header_uses_k_without_its_number_of_clients(html, view_id):
    view = _view(html, view_id)
    if view_id == "modelos":
        view = view[:view.index('<details class="technical" id="models-technical">')]
    for header in re.findall(r"<th[^>]*>(.*?)</th>", view, re.S):
        assert not re.search(r"\bK\b|K\*", header), header


def test_every_k_figure_shown_is_a_k_applied_of_the_json(sample, html):
    allowed = {format_count(k) for k in _k_by_label(sample).values()}
    shown = []
    for view_id in ("modelos", "estres"):
        view = _view(html, view_id)
        shown += re.findall(r"llamando a ([\d.]+) clientes", view)
        shown += re.findall(r"Capacidad de hoy: ([\d.]+) clientes", view)
        shown += re.findall(r'<span data-k="[^"]+">([^<]+)</span>', view)
        shown += re.findall(r'data-k-applied="[^"]+">([^<]+)<', view)
    assert shown and set(shown) <= allowed


def test_the_comparisons_say_how_many_clients_were_called(sample, html):
    view = _view(html, "modelos")
    for e in _compared(sample):
        row = re.search(rf'<tr data-comparison="{e["target"]}.{e["label"]}.{e["model_id"]}">(.*?)</tr>', view, re.S)
        cell = re.search(r'data-k-applied="[^"]+">([^<]+)<', row.group(1)).group(1)
        assert cell == format_count(e["k_applied"])
    assert "Clientes llamados (capacidad de hoy)" in view


def test_stress_warnings_use_plain_names_and_no_k(sample, html):
    view = _view(html, "estres")
    for label, evaluations in _evaluated_by_label(sample).items():
        for e in evaluations:
            warning = re.search(rf'data-sim-warning="{label}.{e["model_id"]}">([^<]*)<', view)
            if warning:
                assert warning.group(1).startswith(_plain_name(e["model_id"]) + ":")
                assert "mejor número de contactos" in warning.group(1) and "K*" not in warning.group(1)
    assert "<td>Al azar</td>" in view
    script = (ROOT / "src" / "predict360" / "dashboard_assets" / "simulator.js").read_text(encoding="utf-8")
    assert "row.model_id + \": la capacidad" not in script and "K* (" not in script
    raw = re.search(r'<script type="application/json" id="sim-data">(.*?)</script>', view, re.S).group(1)
    for label, entry in json.loads(raw)["labels"].items():
        for m in entry["models"]:
            assert m["name"] == _plain_name(m["model_id"])


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


def _risk_row(view, risk_id):
    return re.search(rf'<tr data-risk="{risk_id}">(.*?)</tr>', view, re.S).group(1)


def test_risks_are_shown_in_spanish_with_the_original_in_the_detail(sample, html):
    view = _view(html, "gestion")
    original = next(r for r in sample["management"]["risks"] if r["risk_id"] == "R-01")
    row = _risk_row(view, "R-01")
    visible = _visible(row)
    for words in ("Calidad de datos", "Los registros pueden estar incompletos o fragmentados", "Alta", "Alto",
                  "En mitigación"):
        assert words in visible, words
    assert original["description"] not in visible and original["category"] not in visible
    assert original["description"] in row                                     # kept, folded
    detail = view[view.index('id="risks-technical"'):]
    for r in sample["management"]["risks"]:
        assert escape(r["description"]) in detail and r["category"] in detail


def test_a_risk_whose_text_changed_shows_the_original(sample):
    # a stale translation must never pass for the register's text
    data = copy.deepcopy(sample)
    risk = next(r for r in data["management"]["risks"] if r["risk_id"] == "R-01")
    risk["description"] = "Records arrive late from the core banking system"
    assert "Records arrive late from the core banking system" in _visible(_risk_row(_management(data), "R-01"))


def test_a_risk_translation_takes_its_numbers_from_the_original(sample):
    data = copy.deepcopy(sample)
    risk = next(r for r in data["management"]["risks"] if r["risk_id"] == "R-04")
    risk["description"] = risk["description"].replace("125000", "99000")
    visible = _visible(_risk_row(_management(data), "R-04"))
    assert "99.000 clientes" in visible and "Ley 1581" in visible


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
