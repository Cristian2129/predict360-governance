"""Station 12 (part): renders the committee dashboard as ONE self-contained index.html.

The page is built in Python from ``dashboard_data.json`` (contract ``dashboard_data_v1``),
so it opens with a double click without network, from GitHub Pages, and inside FinBank:

- CSS is inlined from ``dashboard_assets/styles.css``; no external resources.
- Views and the 6-step guided mode are anchors (``#resumen``, ``#guia-1``) shown with
  CSS ``:target``; no JavaScript is needed to navigate.
- Every figure comes from the JSON and is only formatted, in Spanish, by ``formatting.py``
  (the same formatter Gate 3 uses); the source has no hand-written figures. Text from the JSON is HTML-escaped.
- ``write(..., publish=True)`` refuses non-synthetic data: only the synthetic demo run is
  published; a real FinBank run is rendered for local use inside the bank only.

- Trace a figure (B12b): every registered figure shown carries ``data-figure-id`` and a
  ``<details>`` with its output file and hash, path, script, commit and sources. A figure
  that is not registered is shown without a trace, never with an invented one.
- The Data and lineage view lists the registered figures, sources and outputs, explains the
  log status and says that its manifest is a snapshot taken at export.

Charts and the stress simulator arrive in B12b-2; the data quality part of the Data view and
the Models, Management and Handover views in B12c.

Usage:
    python -m src.predict360.dashboard_render --data runs/<run_id>/dashboard_data.json \\
        --out runs/<run_id>/index.html [--publish]
"""
from __future__ import annotations

import argparse
import json
import sys
from html import escape
from pathlib import Path

from src.predict360.dashboard_contract import validate_dashboard_data
from src.predict360.formatting import DASH, format_cop_m, format_count, format_figure, format_pct

ASSETS_DIR = Path(__file__).resolve().parent / "dashboard_assets"

TABS = [
    ("resumen", "Resumen"),
    ("datos", "Datos y linaje"),
    ("modelos", "Modelos"),
    ("estres", "Estrés"),
    ("gestion", "Gestión"),
    ("entrega", "Entrega a FinBank"),
]
GUIDED_STEPS = [
    {"tab": "resumen", "title": "Correr el pipeline y refrescar el tablero",
     "text": "Un solo comando (run_pipeline.py --config config/synthetic.yaml) corre las doce "
             "estaciones y escribe este tablero. Revise la exposición, la conciliación y los tres gates."},
    {"tab": "datos", "title": "Romper los datos",
     "text": "Con un archivo defectuoso, el Gate 1 se pone en rojo y dice qué regla falló."},
    {"tab": "resumen", "title": "Rastrear una cifra hasta su origen",
     "text": "Abra el rastreo de la exposición de mora: archivo de origen, script, commit y hash."},
    {"tab": "modelos", "title": "Comparar modelos",
     "text": "Compare los modelos contra la regla base y el azar, revise las rebanadas y vea una "
             "ficha rechazada con su motivo."},
    {"tab": "estres", "title": "Mover el simulador",
     "text": "Cambie capacidad, efectividad y costo por contacto; observe el valor neto en COP y K*."},
    {"tab": "gestion", "title": "Gestión, evidencia y consistencia",
     "text": "Valor ganado, SPI, CPI y EAC contra el techo del presupuesto; registro de evidencia y Gate 3."},
]
TARGET_NAMES = {"delinquency": "Mora temprana", "churn": "Fuga de clientes preferenciales"}
GATE_NAMES = {"gate1": "Gate 1 · Datos", "gate2": "Gate 2 · Fichas de modelo", "gate3": "Gate 3 · Consistencia"}
VERDICTS = {"authorized_for_shadow_deployment": ("Autorizado a despliegue en sombra", "ok"),
            "not_authorized": ("No autorizado", "bad")}
REASON_CODES = {"authorized": "", "insufficient_evidence": "Evidencia insuficiente",
                "does_not_beat_baseline": "No supera la regla", "no_baseline": "Sin regla base comparable",
                "no_candidate": "Sin modelo candidato"}
OUTCOMES = {"beats": ("Supera la regla", "ok"), "insufficient_evidence": ("Evidencia insuficiente", "warn"),
            "does_not_beat_baseline": ("No supera la regla", "bad")}
LOG_STATUS = {
    "OK": ("ok", "La cadena de hashes del log de linaje está íntegra: ninguna corrida anterior fue alterada."),
    "TAMPERED": ("bad", "El log de linaje fue alterado: la cadena de hashes no coincide. "
                        "No confíe en estas cifras hasta revisarlo."),
    "NOT_CHECKED": ("warn", "El log no se verificó: esta es la primera corrida registrada en él."),
}
SNAPSHOT_NOTE = ("Foto del manifiesto al exportar; el manifiesto final registra también este archivo y el tablero.")
__all__ =["GUIDED_STEPS", "TABS", "format_cop_m", "format_pct", "render", "write"]   # formatters re-exported


def _e(value) -> str:
    return escape(str(value), quote=True)


def _status(value: str) -> str:
    return f'<span class="status {_e(value)}">{_e(value)}</span>'


# --- page parts ------------------------------------------------------------------------

def _banners(meta: dict) -> str:
    items = []
    if meta["sample"]:   # first and loud: Pages shows the fixture until the official run exists
        items.append(("banner-sample", "warn loud",
                      "DATOS DE EJEMPLO · Fixture de desarrollo: no proviene de una corrida del pipeline. "
                      "Ninguna cifra de esta página es un resultado."))
    if meta["synthetic"]:
        items.append(("banner-synthetic", "info",
                      "Datos sintéticos: ninguna cifra corresponde a clientes reales de FinBank."))
    else:
        items.append(("banner-real", "bad", "Datos reales de FinBank: uso interno del banco, no publicar."))
    if meta["scores_simulated"]:
        items.append(("banner-simulated", "info", "Los scores de los modelos son simulados, no entrenados."))
    commit = meta["commit"]
    if commit == "unknown":
        items.append(("banner-commit", "warn",
                      f"No se pudo identificar el commit del código; solo se conoce la versión {_e(meta['code_version'])}."))
    elif commit.endswith("-dirty"):
        items.append(("banner-commit", "warn",
                      "El código tenía cambios sin commit (-dirty): esta no es una corrida oficial."))
    return "".join(f'<div class="banner {cls}" id="{bid}" role="status">{text}</div>' for bid, cls, text in items)


def _header(meta: dict) -> str:
    return (
        '<header class="top"><h1>FinBank Predict360 · Tablero del comité</h1>'
        f'<span class="run">Corrida {_e(meta["run_id"])} · {_e(meta["generated_at"])} · '
        f'commit {_e(meta["commit"][:12])} · v{_e(meta["code_version"])}</span></header>'
    )


def _nav() -> str:
    tabs = "".join(f'<a href="#{tab_id}">{label}</a>' for tab_id, label in TABS)
    steps = "".join(f'<a href="#guia-{n}">{n}. {_e(s["title"])}</a>' for n, s in enumerate(GUIDED_STEPS, start=1))
    return (f'<nav class="tabs" aria-label="Vistas">{tabs}</nav>'
            f'<nav class="guide" aria-label="Modo guiado"><span class="label">Modo guiado:</span>{steps}</nav>')


# --- trace a figure to its origin --------------------------------------------------------

def _figure_sources(figure_id: str) -> list[str]:
    """Manifest sources a figure comes from, by the family of its id."""
    family, *rest = figure_id.split(".")
    if family == "exposure":
        return [rest[0]]
    if family == "models":
        return [rest[0].split("_")[0], "scores"]          # delinquency_30 -> delinquency; churn_3m -> churn
    if family == "management":
        return ["hours_log", "sprint_log"]
    return []


def _trace(figure: dict, data: dict) -> str:
    """<details> with everything needed to rebuild the figure: output, path, script, commit, sources."""
    manifest = data["lineage"]["manifest"]
    output = next((o for o in manifest["outputs"] if o["file"] == figure["file"]), None)
    sources = {s["name"]: s for s in manifest["sources"]}
    listed = [sources[n] for n in _figure_sources(figure["figure_id"]) if n in sources]
    source_rows = "".join(f'<dt>Fuente · {_e(s["name"])}</dt><dd>{_e(s["file"])}<br><code>{_e(s["sha256"])}</code></dd>'
                          for s in listed) or "<dt>Fuentes</dt><dd>sin fuente registrada en el manifiesto</dd>"
    digest = f'<br><code>{_e(output["sha256"])}</code>' if output else ""
    return (
        f'<details class="trace" data-trace="{_e(figure["figure_id"])}"><summary>Rastrear</summary><dl class="kv">'
        f'<dt>Cifra</dt><dd><code>{_e(figure["figure_id"])}</code> = {_e(format_figure(figure["value"], figure["unit"], "es"))}</dd>'
        f'<dt>Archivo de salida</dt><dd>{_e(figure["file"])}{digest}</dd>'
        f'<dt>Ruta en el archivo</dt><dd><code>{_e(figure["path"])}</code></dd>'
        f'<dt>Script</dt><dd>{_e(figure["script"])}</dd>'
        f'<dt>Commit</dt><dd><code>{_e(data["meta"]["commit"])}</code></dd>'
        f'{source_rows}</dl></details>'
    )


def _traced(figure_id: str, data: dict) -> tuple[str, str]:
    """(attribute, trace) for a registered figure; nothing for one that is not registered."""
    figure = next((f for f in data["lineage"]["figures"] if f["figure_id"] == figure_id), None)
    if figure is None:
        return "", ""
    return f' data-figure-id="{_e(figure_id)}"', _trace(figure, data)


def _exposure_card(target: str, rec: dict, data: dict) -> str:
    attribute, trace = _traced(f"exposure.{target}.observed_cop_m", data)
    return (
        f'<div class="card"><h3>{TARGET_NAMES[target]}</h3>'
        f'<div class="figure"{attribute}>{format_cop_m(rec["actual_cop_m"])}</div>{trace}'
        '<div class="label-sm">Exposición observada en los datos</div>'
        '<dl class="kv">'
        f'<dt>Cifra del cliente</dt><dd>{format_cop_m(rec["expected_cop_m"])}</dd>'
        f'<dt>Diferencia</dt><dd>{format_cop_m(rec["difference_cop_m"])}</dd>'
        f'<dt>Tolerancia</dt><dd>{format_cop_m(rec["tolerance_cop_m"])}</dd>'
        f'<dt>Conciliación</dt><dd>{_status(rec["status"])}</dd>'
        '</dl></div>'
    )


def _gates_card(gates: dict) -> str:
    counts = gates["gate2"]["counts"]
    detail = {
        "gate1": f'{len(gates["gate1"]["tables"])} tablas validadas',
        "gate2": f'{counts["ADMITTED"]} admitidas · {counts["REJECTED"]} rechazadas · {counts["SKIPPED"]} omitidas',
        "gate3": f'{gates["gate3"]["checked"]} cifras verificadas · {len(gates["gate3"]["mismatches"])} diferencias',
    }
    rows = "".join(
        f'<dt data-gate="{gate}">{GATE_NAMES[gate]}</dt><dd>{_status(gates[gate]["status"])} '
        f'<span class="label-sm">{_e(detail[gate])}</span></dd>'
        for gate in ("gate1", "gate2", "gate3"))
    gate3 = gates["gate3"]
    warning = ""
    if gate3["status"] == "PASS" and not gate3["citations_checked"]:
        warning = ('<p class="note" id="gate3-no-citations">Gate 3 aún no verifica las cifras citadas en el '
                   'informe y la presentación: la corrida oficial lo exige.</p>')
    return f'<div class="card"><h3>Estado de los gates</h3><dl class="kv">{rows}</dl>{warning}</div>'


def _comparisons(target: str, data: dict) -> str:
    """Point difference next to the paired interval, per model and label, against the rule."""
    rows = ""
    for e in sorted((e for e in data["models"]["evaluations"] if e["target"] == target and e["status"] == "evaluated"
                     and e["vs_baseline"]), key=lambda e: (e["model_id"], e["label"])):
        vs = e["vs_baseline"]
        text, cls = OUTCOMES[vs["outcome"]]
        attribute, trace = _traced(f"models.{e['label']}.{e['model_id']}.difference_vs_baseline_cop_m", data)
        rows += (f'<tr data-comparison="{_e(target)}.{_e(e["label"])}.{_e(e["model_id"])}">'
                 f'<td>{_e(e["model_id"])}</td><td>{_e(e["label"])}</td>'
                 f'<td{attribute}>{format_cop_m(vs["difference_cop_m"])}{trace}</td>'
                 f'<td>{format_cop_m(vs["ci_low_cop_m"])} a {format_cop_m(vs["ci_high_cop_m"])}</td>'
                 f'<td><span class="status {cls}">{text}</span></td></tr>')
    if not rows:
        return ""
    return ('<table class="compare"><thead><tr><th>Modelo</th><th>Etiqueta</th>'
            '<th>Diferencia en K</th><th>IC pareado</th><th>Resultado</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def _decisions_card(data: dict) -> str:
    decisions = data["models"]["decisions"]
    if not decisions:
        body = '<p class="label-sm">Sin dictamen: la regla de promoción no se ha ejecutado.</p>'
    else:
        body = ""
        for d in decisions:
            text, cls = VERDICTS[d["verdict"]]
            model = f' · {_e(d["model_id"])}' if d["model_id"] else ""
            code = REASON_CODES[d["reason_code"]]
            code = f' <span class="status warn">{code}</span>' if code else ""
            body += (f'<div class="decision" data-decision="{_e(d["target"])}">'
                     f'<h4>{TARGET_NAMES[d["target"]]}</h4>'
                     f'<span class="status {cls}">{text}</span>{code}{model}'
                     f'{_comparisons(d["target"], data)}'
                     f'<div class="label-sm">{_e(d["reason"])}</div></div>')
    return ('<div class="card"><h3>Dictamen del comité</h3>' + body +
            '<p class="note">Diferencia de valor neto (modelo − regla base) en la misma K, con su intervalo '
            'bootstrap pareado. Se autoriza solo si todo el intervalo supera el margen. El dictamen más alto '
            'posible es «autorizado a despliegue en sombra».</p></div>')


def _run_card(meta: dict) -> str:
    versions = ", ".join(f"{_e(k)} {_e(v)}" for k, v in sorted(meta["contract_versions"].items()))
    return (
        '<div class="card"><h3>Última corrida</h3><dl class="kv">'
        f'<dt>Corrida</dt><dd>{_e(meta["run_id"])}</dd>'
        f'<dt>Configuración</dt><dd>{_e(meta["config"])}</dd>'
        f'<dt>Fecha de corte T</dt><dd>{_e(meta["snapshot_date"])}</dd>'
        f'<dt>Commit</dt><dd>{_e(meta["commit"])}</dd>'
        f'<dt>Versión del código</dt><dd>{_e(meta["code_version"])}</dd>'
        f'<dt>Contratos</dt><dd>{versions}</dd>'
        '</dl></div>'
    )


def _summary(data: dict) -> str:
    tables = data["exposure"]["tables"]
    return (
        '<section class="view" id="resumen"><h2>Resumen</h2>'
        f'<div class="grid">{_exposure_card("delinquency", tables["delinquency"], data)}'
        f'{_exposure_card("churn", tables["churn"], data)}</div>'
        '<p class="note">Son exposición en riesgo, no pérdida. Las cifras del cliente se concilian en cada corrida.</p>'
        f'<div class="grid">{_gates_card(data["gates"])}{_run_card(data["meta"])}</div>'
        f'<div class="stack">{_decisions_card(data)}</div></section>'
    )


# --- data and lineage view -------------------------------------------------------------------

def _log_card(lineage: dict) -> str:
    status = lineage["log_status"]
    cls, text = LOG_STATUS[status]
    manifest = lineage["manifest"]
    head = manifest["lineage_head_sha256"]
    return (
        f'<div class="card" id="log-status"><h3>Log de linaje</h3>'
        f'<p><span class="status {cls}">{_e(status)}</span> {text}</p>'
        '<dl class="kv">'
        f'<dt>Corrida</dt><dd>{_e(manifest["run_id"])}</dd>'
        f'<dt>Abierta</dt><dd>{_e(manifest["created_at"])}</dd>'
        f'<dt>Exportada</dt><dd>{_e(manifest["closed_at"])}</dd>'
        f'<dt>Ancla en el log</dt><dd>{f"<code>{_e(head)}</code>" if head else "primera entrada del log"}</dd>'
        f'<dt>Scores</dt><dd><code>{_e(manifest["scores_sha256"])}</code></dd>'
        '</dl></div>'
    )


def _files_table(entries: list, caption: str, with_name: bool) -> str:
    head = ("<th>Fuente</th>" if with_name else "") + "<th>Archivo</th><th>Filas</th><th>sha256</th>"
    rows = "".join(
        "<tr>" + (f'<td>{_e(e["name"])}</td>' if with_name else "")
        + f'<td>{_e(e["file"])}</td><td>{format_count(e["rows"])}</td><td><code>{_e(e["sha256"])}</code></td></tr>'
        for e in entries)
    return (f'<table class="data"><caption>{caption}</caption><thead><tr>{head}</tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def _figures_table(data: dict) -> str:
    rows = "".join(
        f'<tr data-figure-row="{_e(f["figure_id"])}"><td><code>{_e(f["figure_id"])}</code></td>'
        f'<td>{_e(format_figure(f["value"], f["unit"], "es"))}</td><td>{_e(f["file"])}</td>'
        f'<td><code>{_e(f["path"])}</code></td><td>{_e(f["script"])}</td></tr>'
        for f in data["lineage"]["figures"])
    return ('<table class="data"><caption>Cifras registradas (las que verifica el Gate 3)</caption>'
            '<thead><tr><th>Cifra</th><th>Valor</th><th>Archivo</th><th>Ruta</th><th>Script</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def _lineage_view(data: dict) -> str:
    manifest = data["lineage"]["manifest"]
    return (
        '<section class="view" id="datos"><h2>Datos y linaje</h2>'
        f'<div class="grid">{_log_card(data["lineage"])}</div>'
        f'<p class="note" id="manifest-snapshot">{SNAPSHOT_NOTE}</p>'
        f'<div class="card">{_figures_table(data)}</div>'
        f'<div class="card">{_files_table(manifest["sources"], "Fuentes de la corrida", True)}</div>'
        f'<div class="card">{_files_table(manifest["outputs"], "Salidas de la corrida", False)}</div>'
        '</section>'
    )


# --- stress view: curve and simulator ----------------------------------------------------------

LABEL_NAMES = {"delinquency_30": "Mora a 30 días", "delinquency_60": "Mora a 60 días",
               "churn_3m": "Fuga a 3 meses"}
HYPOTHETICAL = ("Escenario hipotético: no cambia el dictamen, que se fijó con los supuestos registrados en el acta.")


def _by_label(data: dict) -> dict:
    labels: dict = {}
    for e in data["models"]["evaluations"]:
        if e["status"] == "evaluated":
            labels.setdefault(e["label"], []).append(e)
    return {label: sorted(rows, key=lambda e: e["model_id"]) for label, rows in labels.items()}


def _rule(data: dict) -> str:
    return next((e["vs_baseline"]["baseline_model"] for e in data["models"]["evaluations"]
                 if e["status"] == "evaluated" and e.get("vs_baseline")), "baseline_rule")


def simulator_data(data: dict) -> dict:
    """What simulator.js needs: the acta's assumptions and, per label and model, the published
    curve plus the evaluator's own numbers for the browser self-check."""
    values = {k: v for item in data["assumptions"] for k, v in item["value"].items()}
    return {
        "defaults": {"capacity_share": values["value.default_capacity_share"],
                     "action_effectiveness": values["value.action_effectiveness"],
                     "loss_given_event": values["value.loss_given_event"],
                     "cost_per_contact_cop": values["value.cost_per_contact_cop"]},
        "rule": _rule(data),
        "labels": {label: {"target": rows[0]["target"], "models": [{
            "model_id": e["model_id"], "n_clients": e["n_clients"],
            "event_exposure_cop_m": e["event_exposure_cop_m"], "k_applied": e["k_applied"],
            "k_star_k": e["k_star"]["k"], "at_k_net_value_cop_m": e["at_k"]["net_value_cop_m"],
            "random_net_value_cop_m": e["random_at_k"]["net_value_cop_m"],
            "curve": [{"k": p["k"], "captured_cop_m": p["captured_cop_m"], "net_value_cop_m": p["net_value_cop_m"]}
                      for p in e["curve"]]} for e in rows]}
            for label, rows in _by_label(data).items()},
    }


def curve_svg(label: str, evaluations: list, capacity_k: float | None = None) -> str:
    """Net value against K for each model, the random line and K*; reusable by the Models view.
    Drawn with the assumptions of the acta (the values the evaluator published)."""
    width, height, left, right, top, bottom = 640, 300, 100, 16, 16, 40   # left fits "COP -1.358 M"
    n = max(e["n_clients"] for e in evaluations)
    last = evaluations[0]["curve"][-1]
    nets = [p["net_value_cop_m"] for e in evaluations for p in e["curve"]] + [0.0, last["net_value_cop_m"]]
    low, high = min(nets), max(nets)
    span = (high - low) or 1.0
    xscale = (width - left - right) / n
    x = lambda k: left + xscale * k
    y = lambda v: top + (high - v) / span * (height - top - bottom)
    parts = [f'<line class="axis" data-zero="{_e(label)}" x1="{left}" y1="{y(0):.1f}" x2="{width - right}" '
             f'y2="{y(0):.1f}"/>']
    for i, e in enumerate(evaluations):
        points = " ".join(f"{x(p['k']):.1f},{y(p['net_value_cop_m']):.1f}" for p in e["curve"])
        parts.append(f'<polyline class="series s{i}" data-series="{_e(e["model_id"])}" points="{points}"/>')
        star = e["k_star"]
        parts.append(f'<circle class="kstar s{i}" data-kstar="{_e(e["model_id"])}" cx="{x(star["k"]):.1f}" '
                     f'cy="{y(star["net_value_cop_m"]):.1f}" r="4"><title>K* {_e(e["model_id"])}: '
                     f'{format_count(star["k"])} clientes, {format_cop_m(star["net_value_cop_m"])}</title></circle>')
    parts.append(f'<polyline class="series random" data-series="random" '
                 f'points="{x(0):.1f},{y(0):.1f} {x(last["k"]):.1f},{y(last["net_value_cop_m"]):.1f}"/>')
    if capacity_k is not None:
        parts.append(f'<line class="capacity" data-capacity-line="{_e(label)}" data-x0="{left}" '
                     f'data-xscale="{xscale!r}" x1="{x(capacity_k):.1f}" y1="{top}" x2="{x(capacity_k):.1f}" '
                     f'y2="{height - bottom}"/>')
    parts += [f'<text class="tick" data-tick="high" x="{left - 6}" y="{y(high) + 4:.1f}" text-anchor="end">'
              f'{format_cop_m(high)}</text>',
              f'<text class="tick" data-tick="low" x="{left - 6}" y="{y(low) + 4:.1f}" text-anchor="end">'
              f'{format_cop_m(low)}</text>',
              f'<text class="tick" x="{left}" y="{height - bottom + 16}">0</text>',
              f'<text class="tick" x="{width - right}" y="{height - bottom + 16}" text-anchor="end">'
              f'{format_count(n)} clientes</text>',
              f'<text class="tick" x="{(left + width - right) / 2:.0f}" y="{height - 6}" text-anchor="middle">'
              'Clientes contactados (K)</text>']
    title = f"Valor neto en COP según K · {LABEL_NAMES.get(label, label)}"
    plot_h = height - top - bottom
    return (f'<svg class="curve" data-curve="{_e(label)}" data-x0="{left}" data-xscale="{xscale!r}" '
            f'data-top="{top}" data-plot-h="{plot_h}" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="{_e(title)}"><title>{_e(title)}</title>{"".join(parts)}</svg>')


def _legend(evaluations: list) -> str:
    items = "".join(f'<li><span class="swatch s{i}"></span>{_e(e["model_id"])}</li>' for i, e in enumerate(evaluations))
    return (f'<ul class="legend">{items}<li><span class="swatch random"></span>azar</li>'
            '<li><span class="swatch capacity"></span>K aplicado por capacidad</li>'
            '<li><span class="dot"></span>K* (óptimo sin restricción)</li></ul>')


def _stress_table(label: str, evaluations: list, rule: str) -> str:
    rule_net = next((e["at_k"]["net_value_cop_m"] for e in evaluations if e["model_id"] == rule), None)
    rows, warnings = "", ""
    for e in evaluations:
        key = f'{label}.{e["model_id"]}'
        net = e["at_k"]["net_value_cop_m"]
        diff = DASH if e["model_id"] == rule or rule_net is None else format_cop_m(net - rule_net)
        rows += (f'<tr><td>{_e(e["model_id"])}</td>'
                 f'<td data-sim-kstar="{_e(key)}">{format_count(e["k_star"]["k"])}</td>'
                 f'<td data-sim-kapplied="{_e(key)}">{format_count(e["k_applied"])}</td>'
                 f'<td data-sim-net="{_e(key)}">{format_cop_m(net)}</td>'
                 f'<td data-sim-diff="{_e(key)}">{diff}</td></tr>')
        if e["k_star"]["k"] > e["k_applied"]:
            warnings += (f'<p class="sim-warning" data-sim-slot="{_e(key)}" data-sim-warning="{_e(key)}">'
                         f'{_e(e["model_id"])}: la capacidad ({format_count(e["k_applied"])} clientes) queda por '
                         f'debajo de K* ({format_count(e["k_star"]["k"])}): más capacidad de gestión aumentaría '
                         'el valor neto.</p>')
        else:
            warnings += f'<p class="sim-warning" data-sim-slot="{_e(key)}" hidden></p>'
    random_net = evaluations[0]["random_at_k"]["net_value_cop_m"]
    rows += (f'<tr class="random"><td>azar</td><td>{DASH}</td><td>{DASH}</td>'
             f'<td data-sim-net="{_e(label)}.random">{format_cop_m(random_net)}</td><td>{DASH}</td></tr>')
    return ('<table class="compare"><thead><tr><th>Modelo</th><th>K* de la curva</th><th>K aplicado</th>'
            f'<th>Valor neto en K aplicado</th><th>Diferencia vs {_e(rule)}<br><span class="label-sm">'
            'estimación puntual, sin intervalo</span></th></tr></thead>'
            f'<tbody>{rows}</tbody></table>{warnings}')


def _stress_view(data: dict) -> str:
    sim = simulator_data(data)
    d = sim["defaults"]
    script = (ASSETS_DIR / "simulator.js").read_text(encoding="utf-8")
    payload = json.dumps(sim, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    cards = ""
    for label, evaluations in _by_label(data).items():
        cards += (f'<div class="card" data-sim-label="{_e(label)}"><h3>{_e(LABEL_NAMES.get(label, label))}</h3>'
                  f'{curve_svg(label, evaluations, evaluations[0]["k_applied"])}{_legend(evaluations)}'
                  f'{_stress_table(label, evaluations, sim["rule"])}</div>')
    if not cards:
        cards = '<div class="pending">Sin modelos evaluados: no hay curvas que simular.</div>'
    return (
        '<section class="view" id="estres"><h2>Estrés</h2>'
        f'<p class="banner warn" id="sim-hypothetical" role="note">{HYPOTHETICAL}</p>'
        '<form class="card sim-controls" id="sim-controls" onsubmit="return false">'
        '<label>Capacidad de gestión (% de clientes) <output id="sim-capacity-out">'
        f'{format_pct(d["capacity_share"])}</output>'
        f'<input type="range" id="sim-capacity" min="1" max="100" step="1" value="{round(d["capacity_share"] * 100)}"></label>'
        '<label>Efectividad de la acción <output id="sim-effectiveness-out">'
        f'{format_pct(d["action_effectiveness"])}</output>'
        f'<input type="range" id="sim-effectiveness" min="0" max="100" step="5" '
        f'value="{round(d["action_effectiveness"] * 100)}"></label>'
        f'<label>Costo por contacto <output id="sim-cost-out">COP {format_count(d["cost_per_contact_cop"])}</output>'
        f'<input type="range" id="sim-cost" min="0" max="200000" step="1000" value="{d["cost_per_contact_cop"]}"></label>'
        '<button type="button" id="sim-reset">Restablecer supuestos</button>'
        f'<p class="note">Pérdida por evento fija en {format_pct(d["loss_given_event"])} de la exposición. '
        'Las curvas, K*, la línea de capacidad y la tabla se recalculan con los controles. '
        'Sin JavaScript se muestran los valores del acta.</p></form>'
        '<p class="note" id="sim-status" role="status" hidden></p>'
        f'{cards}'
        f'<script type="application/json" id="sim-data">{payload}</script>'
        f'<script>{script}</script></section>'
    )


def _pending(tab_id: str, label: str) -> str:
    return (f'<section class="view" id="{tab_id}"><h2>{label}</h2>'
            '<div class="pending">Vista en construcción.</div></section>')


def _guided() -> str:
    labels = dict(TABS)
    total = len(GUIDED_STEPS)
    out = []
    for n, step in enumerate(GUIDED_STEPS, start=1):
        actions = [f'<a href="#{step["tab"]}">Ir a {labels[step["tab"]]}</a>']
        if n > 1:
            actions.append(f'<a href="#guia-{n - 1}">Anterior</a>')
        if n < total:
            actions.append(f'<a href="#guia-{n + 1}">Siguiente</a>')
        actions.append('<a href="#resumen">Salir del modo guiado</a>')
        out.append(
            f'<section class="view" id="guia-{n}"><div class="step"><h2>Paso {n} de {total} · {_e(step["title"])}</h2>'
            f'<p>{_e(step["text"])}</p><div class="actions">{"".join(actions)}</div></div></section>')
    return "".join(out)


def render(data: dict) -> str:
    """The complete page. Raises ValueError if the data does not meet dashboard_data_v1."""
    errors = validate_dashboard_data(data)
    if errors:
        raise ValueError("dashboard_data_v1: " + "; ".join(errors[:5]))
    css = (ASSETS_DIR / "styles.css").read_text(encoding="utf-8")
    views = (_summary(data) + _lineage_view(data) + _pending("modelos", dict(TABS)["modelos"]) + _stress_view(data)
             + "".join(_pending(t, label) for t, label in TABS[4:]) + _guided())
    return (
        '<!doctype html>\n<html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Predict360 · Tablero del comité</title>'
        f'<style>{css}</style></head><body>'
        f'<div class="banners">{_banners(data["meta"])}</div>{_header(data["meta"])}{_nav()}'
        f'<main>{views}</main>'
        '<footer>Generado por dashboard_render.py desde dashboard_data.json; ninguna cifra se escribe a mano.</footer>'
        '</body></html>\n'
    )


def write(data: dict, path: str | Path, publish: bool = False) -> Path:
    if publish and not data["meta"]["synthetic"]:
        raise ValueError("Only synthetic runs are published; a real FinBank run stays inside the bank")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(data), encoding="utf-8", newline="\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the committee dashboard as one index.html.")
    parser.add_argument("--data", required=True, help="dashboard_data.json")
    parser.add_argument("--out", required=True, help="index.html to write")
    parser.add_argument("--publish", action="store_true", help="refuse non-synthetic data (public site)")
    args = parser.parse_args(argv)
    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    path = write(data, args.out, publish=args.publish)
    print(f"Dashboard: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
