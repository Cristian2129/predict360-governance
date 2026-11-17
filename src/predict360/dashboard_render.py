"""Station 12 (part): renders the committee dashboard as ONE self-contained index.html.

The page is built in Python from ``dashboard_data.json`` (contract ``dashboard_data_v1``),
so it opens with a double click without network, from GitHub Pages, and inside FinBank:

- CSS is inlined from ``dashboard_assets/styles.css``; no external resources.
- Views are anchors (``#resumen``, ``#modelos``) shown with CSS ``:target``; no JavaScript is
  needed to navigate. There is no guided mode: the story is told in the presentation.
- Every figure comes from the JSON and is only formatted, in Spanish, by ``formatting.py``
  (the same formatter Gate 3 uses); the source has no hand-written figures. Text from the JSON is HTML-escaped.
- ``write(..., publish=True)`` refuses non-synthetic data: only the synthetic demo run is
  published; a real FinBank run is rendered for local use inside the bank only.

- Trace a figure (B12b): every registered figure shown carries ``data-figure-id`` and a
  ``<details>`` with its output file and hash, path, script, commit and sources. A figure
  that is not registered is shown without a trace, never with an invented one.
- The Data and lineage view lists the registered figures, sources and outputs, explains the
  log status and says that its manifest is a snapshot taken at export.

Every chart colours a model by its id, never by its position: Regla actual grey, Modelo A
orange, Modelo B blue, azar dotted grey; green and amber are kept for results.

Usage:
    python -m src.predict360.dashboard_render --data runs/<run_id>/dashboard_data.json \\
        --out runs/<run_id>/index.html [--publish]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import date
from html import escape
from pathlib import Path

from src.predict360.dashboard_contract import validate_dashboard_data
from src.predict360.evaluator import _contact_cost_cop_m, _gain_cop_m
from src.predict360.formatting import (DASH, format_cop_m, format_count, format_decimal, format_figure,
                                       format_pct, format_ratio)

ASSETS_DIR = Path(__file__).resolve().parent / "dashboard_assets"

TABS = [
    ("resumen", "Resumen"),
    ("datos", "Datos"),
    ("trazabilidad", "Trazabilidad"),
    ("modelos", "Modelos"),
    ("estres", "Decisión en COP"),
    ("gestion", "Gestión"),
]
TAB_ICONS = {"resumen": "home", "datos": "db", "trazabilidad": "route", "modelos": "model", "estres": "coin", "gestion": "calendar"}
# The ONE place where technical ids get their name for a reader; ids stay in «Detalle técnico» only
PLAIN_NAMES = {
    "delinquency": "Mora temprana", "churn": "Fuga de clientes preferenciales",
    "delinquency_30": "Mora a 30 días", "delinquency_60": "Mora a 60 días", "churn_3m": "Fuga a 3 meses",
    "baseline_rule": "Regla actual", "model_a": "Modelo A", "model_b": "Modelo B", "model_c": "Modelo C",
    "random": "Al azar", "tenure_months": "antigüedad",
}
GATE_NAMES = {"gate1": "Gate 1 · Datos", "gate2": "Gate 2 · Fichas de modelo", "gate3": "Gate 3 · Consistencia"}
CONTROL_NAMES = {"gate1": ("db", "Datos"), "gate2": ("file", "Fichas de modelo"),
                 "gate3": ("check", "Consistencia de cifras")}
SUMMARY_QUESTION = "¿Cuánto está en riesgo y podemos confiar en la respuesta?"
EXPOSURE_NOTE = ("Son exposición en riesgo, no pérdida. El dictamen más alto posible es «autorizado a despliegue "
                 "en sombra».")
ICONS = {   # 24x24 strokes, drawn inline: no icon font, no network
    "home": '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
    "db": '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/>'
          '<path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    "model": '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M9 9h6v6H9z"/>'
             '<path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3"/>',
    "coin": '<circle cx="12" cy="12" r="9"/><path d="M15 9.5c-.5-1-1.6-1.5-3-1.5-1.9 0-3 .9-3 2s1 1.7 3 2 3 .9 3 '
            '2-1.1 2-3 2c-1.4 0-2.5-.5-3-1.5M12 6v2M12 16v2"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "route": '<circle cx="6" cy="19" r="2.5"/><circle cx="18" cy="5" r="2.5"/><path d="M8.5 19H15a3.5 3.5 0 0 0 0-7H9a3.5 3.5 0 0 1 0-7h6.5"/>',
    "alert": '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18v.5"/>',
    "shield": '<path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
    "file": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 13h6M9 17h6"/>',
    "scale": '<path d="M12 4v16M5 20h14M4 8h16"/><path d="M7 8l-3 6a3 3 0 0 0 6 0zM17 8l-3 6a3 3 0 0 0 6 0z"/>',
}
PILL_ICONS = {"ok": "check", "warn": "alert", "bad": "alert"}
CARD_RULES = {"complete_card": "ficha incompleta", "traceable": "sin trazabilidad",
              "temporal_split": "partición no temporal", "preprocessing_train_only": "posible fuga en el preprocesamiento",
              "status_backed": "estado sin aprobación", "intervention_declared": "intervención no declarada",
              "baselines_compared": "líneas base no comparadas", "status": "retirada"}
VERDICTS = {"authorized_for_shadow_deployment": ("Autorizado a despliegue en sombra", "ok"),
            "not_authorized": ("No autorizado", "bad")}
OUTCOMES = {"beats": ("Supera la regla", "ok"), "insufficient_evidence": ("Evidencia insuficiente", "warn"),
            "does_not_beat_baseline": ("No supera la regla", "bad")}
SNAPSHOT_NOTE = ("Foto del manifiesto al exportar; el manifiesto final registra también este archivo y el tablero.")
__all__ = ["TABS", "format_cop_m", "format_pct", "render", "write"]   # formatters re-exported


def _e(value) -> str:
    return escape(str(value), quote=True)


def _status(value: str) -> str:
    return f'<span class="status {_e(value)}">{_e(value)}</span>'


def _plain(key) -> str:
    """Reader's name of a technical id (escaped); an unknown id is shown as it is."""
    return _e(PLAIN_NAMES.get(key, key))


def _icon(name: str, size: int = 20) -> str:
    return (f'<svg class="ico" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>')


def _pill(cls: str, text: str, pill_id: str = "", attrs: str = "") -> str:
    """Soft status pill: colour, icon AND words, never colour alone. ``text`` is already HTML."""
    attribute = (f' id="{pill_id}" role="status"' if pill_id else "") + attrs
    return f'<span class="pill {cls}"{attribute}>{_icon(PILL_ICONS[cls], 14)}<span>{text}</span></span>'


def _plural(n: int, one: str, many: str) -> str:
    return f"{format_count(n)} {one if n == 1 else many}"


# --- page parts ------------------------------------------------------------------------

def _banners(meta: dict) -> str:
    """Full-width strips only where a reader could be misled: the fixture, or real FinBank data."""
    items = []
    if meta["sample"]:   # first and loud: Pages shows the fixture until the official run exists
        items.append(("banner-sample", "warn loud",
                      "DATOS DE EJEMPLO · Fixture de desarrollo: no proviene de una corrida del pipeline. "
                      "Ninguna cifra de esta página es un resultado."))
    if not meta["synthetic"]:
        items.append(("banner-real", "bad", "Datos reales de FinBank: uso interno del banco, no publicar."))
    return "".join(f'<div class="banner {cls}" id="{bid}" role="status">{text}</div>' for bid, cls, text in items)


def _commit_warning(meta: dict) -> str:
    commit = meta["commit"]
    if commit == "unknown":
        return _pill("warn", "No se pudo identificar el commit del código; solo se conoce la versión "
                             f"{_e(meta['code_version'])}.", "banner-commit")
    if commit.endswith("-dirty"):
        return _pill("warn", "El código tenía cambios sin commit: esta no es una corrida oficial.", "banner-commit")
    return ""


def _header(meta: dict) -> str:
    simulated = ' · <span id="banner-simulated">scores simulados</span>' if meta["scores_simulated"] else ""
    if meta["synthetic"]:
        tag = f'<span class="tag" id="banner-synthetic">Datos sintéticos{simulated}</span>'
    else:
        tag = '<span class="tag" id="banner-simulated">Scores simulados</span>' if meta["scores_simulated"] else ""
    return (
        '<header class="top"><div><h1>FinBank Predict360 · Tablero del comité</h1>'
        f'<div class="run">Corrida {_e(meta["run_id"])} · corte {_e(meta["snapshot_date"])} · '
        f'commit {_e(meta["commit"][:12])} · v{_e(meta["code_version"])}</div></div>'
        f'<div class="tags">{_commit_warning(meta)}{tag}</div></header>'
    )


def _sidebar() -> str:
    links = "".join(f'<a class="nav" href="#{tab_id}">{_icon(TAB_ICONS[tab_id])}<span>{label}</span></a>'
                    for tab_id, label in TABS)
    return (f'<aside class="side"><div class="brand"><span class="mark">{_icon("check", 18)}</span>Predict360</div>'
            f'<nav aria-label="Vistas">{links}</nav></aside>')


def _active_nav_style() -> str:
    """Highlights the link of the view on screen with :target and :has(), without JavaScript."""
    rules = [f'.app:has(#{tab_id}:target) .nav[href="#{tab_id}"]' for tab_id, _ in TABS]
    rules.append('.app:not(:has(section.view:target)) .nav[href="#resumen"]')
    return f'<style>{", ".join(rules)} {{ background: var(--accent-soft); color: var(--accent); }}</style>'


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


def _demo_notes(cards: list[dict]) -> str:
    """A demo card is labelled next to its reason: a rejection must not read as a delivered model."""
    notes = ""
    for card in (c for c in cards if c["demo"]):
        reasons = "; ".join(f'{_e(r["rule"])} ({CARD_RULES.get(r["rule"], r["rule"])})' for r in card["reasons"])
        outcome = f"rechazada por {reasons}" if card["decision"] == "REJECTED" else "admitida"
        notes += (f'<p class="note" data-demo-card="{_e(card["file"])}"><span class="status warn">Ficha de '
                  f'demostración</span> {_e(card["target"])} · {_e(card["model_id"])}, {outcome}. PCM la incluye '
                  'a propósito para mostrar a Gate 2 deteniendo una fuga de datos: no es un modelo entregado.</p>')
    return notes


def _comparisons(target: str, data: dict) -> str:
    """Point difference next to the paired interval, per model and label, against the rule."""
    rows = ""
    for e in sorted((e for e in data["models"]["evaluations"] if e["target"] == target and e["status"] == "evaluated"
                     and e["vs_baseline"]), key=lambda e: (e["model_id"], e["label"])):
        vs = e["vs_baseline"]
        text, cls = OUTCOMES[vs["outcome"]]
        attribute, trace = _traced(f"models.{e['label']}.{e['model_id']}.difference_vs_baseline_cop_m", data)
        rows += (f'<tr data-comparison="{_e(target)}.{_e(e["label"])}.{_e(e["model_id"])}">'
                 f'<td>{_plain(e["model_id"])}</td><td>{_plain(e["label"])}</td>'
                 f'<td class="num" data-k-applied="{_e(e["label"])}">{format_count(e["k_applied"])}</td>'
                 f'<td{attribute}>{format_cop_m(vs["difference_cop_m"])}{trace}</td>'
                 f'<td>{format_cop_m(vs["ci_low_cop_m"])} a {format_cop_m(vs["ci_high_cop_m"])}</td>'
                 f'<td><span class="status {cls}">{text}</span></td></tr>')
    if not rows:
        return ""
    return ('<table class="compare"><thead><tr><th>Modelo</th><th>Horizonte</th>'
            '<th>Clientes llamados (capacidad de hoy)</th><th>Ventaja</th><th>Intervalo</th>'
            '<th>Resultado</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


# --- summary: how much is at risk, and can the answer be trusted? ---------------------------------

def _authorized_decisions(data: dict) -> list[dict]:
    return [d for d in data["models"]["decisions"] if d["verdict"] == "authorized_for_shadow_deployment"]


def _summary_answer(data: dict) -> str:
    """The answer sentence, generated from the JSON (escaped pieces only)."""
    tables = data["exposure"]["tables"]
    total = sum(t["actual_cop_m"] for t in tables.values())
    off = [name for name, t in tables.items() if t["status"] != "PASS"]
    both = "las dos cifras" if len(tables) == 2 else "las cifras"
    reconciled = (f"y {both} cuadran con las del banco" if not off else
                  f"pero las cifras de {' y '.join(_plain(t) for t in off)} no cuadran con las del banco")
    decisions = data["models"]["decisions"]
    authorized = _authorized_decisions(data)
    if not decisions:
        verdict = "todavía no hay dictamen sobre los modelos"
    elif authorized:
        verdict = "; ".join(f"{_plain(d['target'])} tiene un modelo autorizado a despliegue en sombra "
                            f"({_plain(d['model_id'])})" for d in authorized)
        rest = [d for d in decisions if d not in authorized]
        if rest:
            verdict += f"; en {' y '.join(_plain(d['target']) for d in rest)} la evidencia todavía no alcanza"
    else:
        verdict = "ningún modelo tiene todavía evidencia suficiente para reemplazar la regla actual"
    return f"FinBank tiene {format_cop_m(total)} expuestos entre mora y fuga {reconciled}; {verdict}."


def _kpi(key: str, icon: str, tone: str, label: str, value: str, pill: str, attribute: str = "") -> str:
    return (f'<article class="kpi" data-kpi="{key}"><div class="kpi-top"><span class="bubble {tone}">{_icon(icon)}'
            f'</span><span class="kpi-label">{label}</span></div><div class="kpi-value"{attribute}>{value}</div>'
            f'{pill}</article>')


def _exposure_kpi(target: str, rec: dict, data: dict) -> str:
    attribute, _ = _traced(f"exposure.{target}.observed_cop_m", data)
    if rec["status"] == "PASS":
        pill = _pill("ok", "Cuadra con la cifra del banco")
    else:
        pill = _pill("bad", f"No cuadra: difiere en {format_cop_m(rec['difference_cop_m'])}")
    return _kpi(_e(target), "coin" if target == "delinquency" else "shield", "blue", f"{_plain(target)} · exposición",
                format_cop_m(rec["actual_cop_m"]), pill, attribute)


def _verdict_kpi(data: dict) -> str:
    decisions = data["models"]["decisions"]
    authorized = _authorized_decisions(data)
    if authorized:
        value, tone = VERDICTS["authorized_for_shadow_deployment"][0], "green"
        pill = _pill("ok", "En sombra: " + ", ".join(_plain(d["target"]) for d in authorized))
    elif decisions:
        codes = [d["reason_code"] for d in decisions]
        code = "insufficient_evidence" if "insufficient_evidence" in codes else codes[0]
        text, cls = DECISION_TAGS[code]
        value, tone, pill = VERDICTS["not_authorized"][0], "amber", _pill(cls, text)
    else:
        value, tone, pill = "Sin dictamen", "amber", _pill("warn", "La regla de promoción no se ejecutó")
    return _kpi("verdict", "scale", tone, "Dictamen del comité", value, pill)


def _control_states(data: dict) -> dict:
    gates = data["gates"]
    status, failed = _data_status(gates["gate1"])
    waivers = {r["waived_by"] for r in failed if r.get("waived_by")}
    gate1 = {"PASS": ("ok", "Cumplen sus contratos"),
             "PASS_WITH_WAIVERS": ("warn", f"Pasan con {_plural(len(waivers), 'excepción aprobada', 'excepciones aprobadas')}"),
             "FAIL": ("bad", "No pasan: no use las cifras de esta corrida")}[status]
    g2 = gates["gate2"]
    if g2["status"] == "PASS":
        counts = g2["counts"]
        demo = sum(c["demo"] and c["decision"] == "REJECTED" for c in data["models"]["cards"])
        text = (f'{_plural(counts["ADMITTED"], "admitida", "admitidas")} · '
                f'{_plural(counts["REJECTED"], "rechazada", "rechazadas")}'
                + (f" ({format_count(demo)} de demostración)" if demo else "")
                + (f' · {_plural(counts["SKIPPED"], "omitida", "omitidas")}' if counts["SKIPPED"] else ""))
        gate2 = ("ok", text)
    else:
        gate2 = ("warn", "No se revisó en esta corrida") if g2["status"] == "NOT_RUN" else \
                ("bad", "Hay fichas con errores: vea Modelos")
    g3 = gates["gate3"]
    if g3["status"] == "NOT_RUN":
        gate3 = ("warn", "No se verificó en esta corrida")
    else:
        n = len(g3["mismatches"])
        gate3 = ("ok" if g3["status"] == "PASS" and not n else "bad",
                 f'{_plural(g3["checked"], "cifra verificada", "cifras verificadas")} · '
                 f'{_plural(n, "diferencia", "diferencias")}')
    return {"gate1": gate1, "gate2": gate2, "gate3": gate3}


def _controls_panel(data: dict) -> str:
    items = ""
    for gate, (cls, text) in _control_states(data).items():
        icon, name = CONTROL_NAMES[gate]
        items += (f'<div class="control" data-gate="{gate}"><span class="bubble soft">{_icon(icon)}</span>'
                  f'<div><p class="control-name">{name}</p>{_pill(cls, _e(text))}</div></div>')
    g3 = data["gates"]["gate3"]
    note = ""
    if g3["status"] == "PASS" and not g3["citations_checked"]:
        note = ('<p class="foot" id="gate3-no-citations">Aún no se verifican las cifras citadas en el informe y la '
                'presentación: lo exige la corrida oficial.</p>')
    return f'<div class="panel"><h3>Controles de esta corrida</h3><div class="controls">{items}</div>{note}</div>'


def _summary_detail(data: dict) -> str:
    meta, gates = data["meta"], data["gates"]
    rows = ""
    for target, rec in data["exposure"]["tables"].items():
        attribute, trace = _traced(f"exposure.{target}.observed_cop_m", data)
        rows += (f'<tr><td>{_plain(target)} <code>{_e(target)}</code></td>'
                 f'<td class="num"><span{attribute}>{format_cop_m(rec["actual_cop_m"])}</span>{trace}</td>'
                 f'<td class="num">{format_cop_m(rec["expected_cop_m"])}</td>'
                 f'<td class="num">{format_cop_m(rec["difference_cop_m"])}</td>'
                 f'<td class="num">{format_cop_m(rec["tolerance_cop_m"])}</td><td>{_status(rec["status"])}</td></tr>')
    reconciliation = ('<table class="data"><caption>Conciliación con las cifras del banco</caption><thead><tr>'
                      '<th>Tabla</th><th class="num">Observada</th><th class="num">Cifra del cliente</th>'
                      '<th class="num">Diferencia</th><th class="num">Tolerancia</th><th>Estado</th></tr></thead>'
                      f'<tbody>{rows}</tbody></table>')
    gate_rows = "".join(f'<tr><td>{GATE_NAMES[g]}</td><td>{_status(gates[g]["status"])}</td></tr>'
                        for g in ("gate1", "gate2", "gate3"))
    decisions = "".join(
        f'<tr data-decision="{_e(d["target"])}"><td>{_plain(d["target"])}</td><td><code>{_e(d["verdict"])}</code></td>'
        f'<td><code>{_e(d["reason_code"])}</code></td><td>{_e(d["model_id"] or DASH)}</td><td>{_e(d["reason"])}</td></tr>'
        for d in data["models"]["decisions"])
    versions = ", ".join(f"{_e(k)} {_e(v)}" for k, v in sorted(meta["contract_versions"].items()))
    run = "".join(f'<dt>{name}</dt><dd><code>{_e(value)}</code></dd>' for name, value in (
        ("Corrida", meta["run_id"]), ("Configuración", meta["config"]), ("Fecha de corte T", meta["snapshot_date"]),
        ("Commit", meta["commit"]), ("Versión del código", meta["code_version"]))) + f"<dt>Contratos</dt><dd>{versions}</dd>"
    return (f'<details class="technical" id="summary-technical"><summary>Detalle técnico</summary>{reconciliation}'
            '<table class="data"><caption>Gates</caption><thead><tr><th>Gate</th><th>Estado</th></tr></thead>'
            f'<tbody>{gate_rows}</tbody></table>{_demo_notes(data["models"]["cards"])}'
            '<table class="data"><caption>Dictamen por objetivo</caption><thead><tr><th>Objetivo</th><th>Veredicto</th>'
            f'<th>Código</th><th>Modelo</th><th>Motivo</th></tr></thead><tbody>{decisions}</tbody></table>'
            f'<h4>Corrida</h4><dl class="kv">{run}</dl></details>')


def _summary(data: dict) -> str:
    tables = data["exposure"]["tables"]
    kpis = "".join(_exposure_kpi(t, tables[t], data) for t in tables) + _verdict_kpi(data)
    return (
        f'<section class="view" id="resumen"><h2 class="view-title">{dict(TABS)["resumen"]}</h2>'
        f'<p class="q">{SUMMARY_QUESTION}</p><p class="answer" id="summary-answer">{_summary_answer(data)}</p>'
        f'<div class="kpis">{kpis}</div>{_controls_panel(data)}{_summary_detail(data)}'
        f'<p class="foot">{EXPOSURE_NOTE}</p></section>'
    )


# --- shared pieces of the redesigned views ---------------------------------------------------------

def _how(*bullets: str) -> str:
    """«¿Cómo se lee?» under every chart: 2-3 bullets, collapsed."""
    items = "".join(f"<li>{b}</li>" for b in bullets)
    return f'<details class="how"><summary>¿Cómo se lee?</summary><ul>{items}</ul></details>'


def _named(name: str, technical: str) -> str:
    """Table cell content: the reader's name first, the technical id in grey below it."""
    return f'<span class="name">{name}</span><code class="id">{_e(technical)}</code>'


def _short(digest: str | None) -> str:
    """A hash cut to 8 characters for the view; the full one lives in «Detalle técnico»."""
    return f'<code class="hash">{_e(digest[:8])}</code>' if digest else DASH


# --- data: can the data of this run be trusted? ------------------------------------------------

DATA_TABLES = ("delinquency", "churn", "scores")
TABLE_NAMES = {"delinquency": "mora", "churn": "fuga", "scores": "scores", "hours_log": "registro de horas"}
DATA_CARD_NAMES = {"delinquency": ("Mora temprana", "coin"), "churn": ("Fuga de clientes preferenciales", "shield"),
                   "scores": ("Scores de los modelos", "model")}
DATA_QUESTION = "¿Se puede confiar en los datos?"
GATE1_ORDER = {"PASS": 0, "PASS_WITH_WAIVERS": 1, "FAIL": 2}
GATE1_CLASS = {"PASS": "ok", "PASS_WITH_WAIVERS": "warn", "FAIL": "bad"}
STEP_NAMES = {"input": "Entrada", "cohort_not_in_arrears_at_T": "Cohorte: sin mora en la fecha de corte",
              "cohort_not_maturing_within_horizon": "Cohorte: el producto no vence dentro del horizonte",
              "excluded_immature_all_horizons": "Excluidos: ventana incompleta en todos los horizontes",
              "labeled": "Etiquetados"}
EVENTS = {"delinquency": ("caerán en mora", "cayeron en mora", "cayó en mora"),
          "churn": ("cancelarán", "cancelaron", "canceló")}
SEGMENTS = (("no_event", "Evaluables sin evento"), ("event", "Con evento"), ("immature", "Sin ventana completa"))
WAIVER_WARNING_DAYS = 60


def _gate1_table(gate1: dict, tables: tuple, caption: str) -> str:
    rows = ""
    for name in tables:
        t = gate1["tables"].get(name)
        if t is None:
            continue
        rules = ""
        for r in t["failed_rules"]:
            critical = " · crítica" if r["critical"] else ""
            waiver = f' · waiver {_e(r["waived_by"])}' if r.get("waived_by") else ""
            pct = r.get("unexpected_pct")                  # None for table-level rules (empty, schema)
            column = f' · {_e(r["column"])}' if r.get("column") else ""
            share = f" · {format_pct(pct / 100)}" if pct is not None else ""
            rules += f'<li><code>{_e(r["rule"])}</code>{column}{share}{critical}{waiver}</li>'
        label = DATA_CARD_NAMES.get(name, (PLAIN_NAMES.get(name, TABLE_NAMES.get(name, name)),))[0]
        rows += (f'<tr data-gate1-table="{_e(name)}"><td>{_named(_e(label), name)}</td><td>{_status(t["status"])}</td>'
                 f'<td class="num">{format_count(t["rows"])}</td>'
                 f'<td><ul class="plain">{rules}</ul>{"" if rules else DASH}</td></tr>')
    return (f'<table class="data"><caption>{caption}</caption><thead><tr><th>Tabla</th><th>Estado</th>'
            f'<th class="num">Filas</th><th>Reglas que fallaron</th></tr></thead><tbody>{rows}</tbody></table>')


def _data_status(gate1: dict) -> tuple[str, list[dict]]:
    """Worst Gate 1 status of FinBank's data tables (PCM's hours log is shown in Gestión)."""
    tables = [gate1["tables"][t] for t in DATA_TABLES if t in gate1["tables"]]
    status = max((t["status"] for t in tables), key=GATE1_ORDER.get, default="PASS")
    return status, [r for t in tables for r in t["failed_rules"]]


def _waiver_fragment(waiver: dict, data: dict) -> str:
    missing = data["quality"]["missing"].get(waiver["table"], {}).get(waiver["column"])
    column = _plain(waiver["column"])
    table = TABLE_NAMES.get(waiver["table"], waiver["table"])
    if waiver["rule"] == "expect_column_values_to_not_be_null" and missing:
        return f'el {format_pct(missing["pct"] / 100)} de la tabla de {_e(table)} no tiene {column} registrada'
    return f'la tabla de {_e(table)} incumple una regla sobre {column}'


def _data_answer(data: dict) -> str:
    gate1 = data["gates"]["gate1"]
    status, failed = _data_status(gate1)
    tables = [t for t in DATA_TABLES if t in gate1["tables"]]
    if status == "FAIL":
        bad = [t for t in tables if gate1["tables"][t]["status"] == "FAIL"]
        n = sum(1 for r in failed if not r.get("waived_by"))
        return (f"No: {_plural(n, 'regla falla', 'reglas fallan')} sin excepción en "
                f"{' y '.join(_e(TABLE_NAMES.get(t, t)) for t in bad)}. No use las cifras de esta corrida.")
    if status == "PASS_WITH_WAIVERS":
        used = {r["waived_by"] for r in failed if r.get("waived_by")}
        waivers = [w for w in data["quality"]["waivers"] if w["id"] in used]
        detail = "; ".join(f'{_waiver_fragment(w, data)}, que se evalúa aparte hasta el {_e(w["expires"])}'
                           for w in waivers)
        return (f"Sí, con {_plural(len(used), 'excepción aprobada', 'excepciones aprobadas')}: las "
                f"{format_count(len(tables))} tablas de FinBank pasan sus controles, pero {detail}.")
    return f"Sí: las {format_count(len(tables))} tablas de FinBank cumplen sus contratos."


def _table_cards(data: dict) -> str:
    gate1, funnels = data["gates"]["gate1"], data["quality"]["labeling_funnel"]
    cards = ""
    for table in DATA_TABLES:
        t = gate1["tables"].get(table)
        if t is None:
            continue
        name, icon = DATA_CARD_NAMES[table]
        if table in funnels:
            size = f'{format_count(funnels[table]["steps"][0]["clients"])} clientes'
            sub = f'<p class="kpi-sub">{_plural(t["rows"], "fila", "filas")} en la muestra</p>'
        else:
            size, sub = f'{format_count(t["rows"])} filas', ""
        unwaived = sum(1 for r in t["failed_rules"] if not r.get("waived_by"))
        pill = {"PASS": ("ok", "Cumple su contrato"), "PASS_WITH_WAIVERS": ("warn", "Pasa con una excepción aprobada"),
                "FAIL": ("bad", f"No pasa: {_plural(unwaived, 'regla', 'reglas')} sin excepción")}[t["status"]]
        cards += (f'<article class="kpi" data-table="{_e(table)}"><div class="kpi-top"><span class="bubble blue">'
                  f'{_icon(icon)}</span><span class="kpi-label">{name}</span></div><div class="kpi-value">{size}</div>'
                  f'{sub}{_pill(*pill)}</article>')
    return f'<div class="kpis" id="data-tables">{cards}</div>'


def missing_svg(table: str, column: str, m: dict, state: str) -> str:
    """Share missing against the contract limit: one bar, one vertical mark, direct labels."""
    width, height, left, right = 460, 64, 4, 112
    w = width - left - right
    vmax = max(m["pct"], m["limit_pct"]) * 1.25 or 1.0
    x = lambda pct: left + w * pct / vmax
    limit = x(m["limit_pct"])
    title = f"{PLAIN_NAMES.get(column, column)} faltante en la tabla de {TABLE_NAMES.get(table, table)}"
    return (f'<svg class="hbar" data-missing="{_e(table)}.{_e(column)}" data-state="{state}" data-x0="{left}" '
            f'data-w="{w}" data-max="{vmax!r}" viewBox="0 0 {width} {height}" role="img" aria-label="{_e(title)}">'
            f'<title>{_e(title)}</title><rect class="track" x="{left}" y="22" width="{w}" height="18" rx="4"/>'
            f'<rect class="value" x="{left}" y="22" width="{_f(w * m["pct"] / vmax)}" height="18" rx="4"/>'
            f'<line class="limit" x1="{_f(limit)}" y1="14" x2="{_f(limit)}" y2="48"/>'
            f'<text class="tick" x="{_f(limit)}" y="60" text-anchor="middle">límite {format_pct(m["limit_pct"] / 100)}'
            f'</text><text class="value-label" x="{_f(x(m["pct"]) + 8)}" y="36">{format_pct(m["pct"] / 100)} faltante'
            '</text></svg>')


def _missing_card(data: dict) -> str:
    waivers = {(w["table"], w["column"]): w["id"] for w in data["quality"]["waivers"]}
    charts, titles = "", []
    for table in DATA_TABLES:
        for column, m in data["quality"]["missing"].get(table, {}).items():
            if m["limit_pct"] is None or m["count"] <= 0:
                continue                       # no contract limit (event dates), or nothing missing
            over = m["pct"] > m["limit_pct"]
            waiver = waivers.get((table, column))
            state = "ok" if not over else ("warn" if waiver else "bad")
            verdict = ("dentro del límite" if not over else
                       f"por encima del límite; se acepta con la excepción {_e(waiver)}" if waiver else
                       "por encima del límite y sin excepción")
            titles.append(f'{_plain(column).capitalize()} falta en el {format_pct(m["pct"] / 100)} de la tabla de '
                          f'{_e(TABLE_NAMES.get(table, table))}, {verdict}')
            charts += (f'<figure>{missing_svg(table, column, m, state)}<figcaption>{format_pct(m["pct"] / 100)} '
                       f'faltante · límite del contrato {format_pct(m["limit_pct"] / 100)}</figcaption></figure>')
    if not charts:
        return ('<div class="card" id="data-missing"><p class="plain" id="missing-none">Ninguna columna con límite del '
                'contrato tiene faltantes.</p></div>')
    return (f'<div class="card" id="data-missing"><h3>{". ".join(titles)}.</h3>{charts}'
            + _how("Cada barra es el porcentaje de filas sin dato en esa columna.",
                   "La marca vertical es el máximo que permite el contrato de datos.",
                   "Solo se muestran columnas con límite y con faltantes; las fechas de evento faltan por diseño.")
            + '</div>')


def _waiver_card(waiver: dict, data: dict) -> str:
    plain = f'{_waiver_fragment(waiver, data)}; no se rellena, se evalúa aparte.'
    plain = plain[0].upper() + plain[1:]
    run_day = date.fromisoformat(data["meta"]["generated_at"][:10])
    start, end = date.fromisoformat(str(waiver["date"])), date.fromisoformat(str(waiver["expires"]))
    days = (end - run_day).days
    span = (end - start).days or 1
    elapsed = 100 * min(max((run_day - start).days / span, 0.0), 1.0)
    soon = days <= WAIVER_WARNING_DAYS
    expiring = ""
    if soon:
        expiring = (f'<p class="note" data-waiver-expiring="{_e(waiver["id"])}">Vence en {format_count(days)} días: '
                    f'renovar o corregir antes del {_e(waiver["expires"])}.</p>')
    return (f'<div class="card" data-waiver="{_e(waiver["id"])}"><h3>Excepción {_e(waiver["id"])} · '
            f'{_plain(waiver["column"])} en la tabla de {_e(TABLE_NAMES.get(waiver["table"], waiver["table"]))}</h3>'
            f'<p class="plain">{plain}</p>'
            f'<div class="timeline" data-waiver-timeline="{_e(waiver["id"])}"><div class="track">'
            f'<span class="elapsed{" soon" if soon else ""}" style="width: {elapsed:.2f}%"></span></div>'
            f'<div class="ends"><span>Aprobada {_e(waiver["date"])}</span><span>Hoy: faltan {format_count(days)} '
            f'días</span><span>Vence {_e(waiver["expires"])}</span></div></div>'
            f'<dl class="kv"><dt>Aprobó</dt><dd>{_e(waiver["approved_by"])}</dd>'
            f'<dt>Riesgo asociado</dt><dd>{_e(waiver["risk"])}</dd></dl>{expiring}'
            f'<details class="technical"><summary>Detalle técnico</summary><dl class="kv">'
            f'<dt>Tabla y columna</dt><dd><code>{_e(waiver["table"])}.{_e(waiver["column"])}</code></dd>'
            f'<dt>Regla</dt><dd><code>{_e(waiver["rule"])}</code></dd><dt>Motivo</dt><dd>{_e(waiver["reason"])}</dd>'
            '</dl></details></div>')


def _horizon_sentence(target: str, label: str, h: dict, total: float) -> str:
    future, past, _ = EVENTS.get(target, ("tendrán el evento", "tuvieron el evento", ""))
    return (f'<p class="plain" data-horizon="{_e(label)}">{_plain(label)}. De '
            f'{format_count(total)} clientes, {format_count(h["mature_clients"])} tienen su ventana de '
            f'{format_count(h["horizon_days"])} días completa; {format_count(total - h["mature_clients"])} se '
            f'excluyen porque aún no se sabe si {future}. De los evaluados, '
            f'{format_count(h["positive_clients"])} {past} (tasa base {format_pct(h["base_rate"])}).</p>')


def _funnel_card(target: str, funnel: dict) -> str:
    total = funnel["steps"][0]["clients"]
    bars, parts = "", []
    for label, h in funnel["horizons"].items():
        values = {"no_event": h["mature_clients"] - h["positive_clients"], "event": h["positive_clients"],
                  "immature": total - h["mature_clients"]}
        segments = "".join(
            f'<span class="seg {kind}" data-segment="{kind}" style="width: {100 * values[kind] / total if total else 0:.4f}%" '
            f'title="{name}: {format_count(values[kind])} clientes"></span>' for kind, name in SEGMENTS)
        bars += (f'<p class="bar-label">{_plain(label)}</p><div class="stacked" data-horizon-bar="{_e(label)}" '
                 f'role="img" aria-label="{_plain(label)}">{segments}</div>'
                 f'{_horizon_sentence(target, label, h, total)}')
        parts.append(f'{format_count(h["mature_clients"])} a {format_count(h["horizon_days"])} días')
    legend = "".join(f'<li><span class="key {kind}"></span>{name}</li>' for kind, name in SEGMENTS)
    unverifiable = [s for s in funnel["steps"] if s.get("status") == "not_verifiable"]
    note = ""
    if unverifiable:
        note = (f'<p class="note" data-not-verifiable="{_e(target)}">'
                f'{_plural(len(unverifiable), "paso del embudo no se puede verificar", "pasos del embudo no se pueden verificar")} '
                'con las columnas que entrega FinBank hoy: vea el Detalle técnico.</p>')
    title = f'{_plain(target)}: de {format_count(total)} clientes se pueden evaluar {" y ".join(parts)}'
    return (f'<div class="card" data-funnel="{_e(target)}"><h3>{title}</h3><ul class="legend">{legend}</ul>{bars}{note}'
            + _how("Cada barra son todos los clientes de la tabla, al 100 %.",
                   "Azul oscuro: clientes con el evento dentro del horizonte; azul claro: evaluables sin evento.",
                   "Gris: clientes cuya ventana aún no termina; no entran en la evaluación porque no se sabe qué pasará.")
            + '</div>')


def _missing_detail(data: dict) -> str:
    waivers = {(w["table"], w["column"]): w["id"] for w in data["quality"]["waivers"]}
    rows = ""
    for table in DATA_TABLES:
        for column, m in data["quality"]["missing"].get(table, {}).items():
            if m["limit_pct"] is None:
                continue
            if m["pct"] <= m["limit_pct"]:
                state = '<span class="status ok">dentro del límite</span>'
            elif (table, column) in waivers:
                state = f'<span class="status warn">con waiver {_e(waivers[(table, column)])}</span>'
            else:
                state = '<span class="status bad">supera el límite</span>'
            rows += (f'<tr data-missing-all="{_e(table)}.{_e(column)}"><td>{_named(_e(TABLE_NAMES.get(table, table)), table)}'
                     f'</td><td>{_named(_plain(column), column)}</td><td class="num">{format_count(m["count"])}</td>'
                     f'<td class="num">{format_pct(m["pct"] / 100)}</td><td class="num">{format_pct(m["limit_pct"] / 100)}'
                     f'</td><td>{state}</td></tr>')
    return ('<table class="data"><caption>Faltantes en todas las columnas con límite del contrato</caption><thead><tr>'
            '<th>Tabla</th><th>Columna</th><th class="num">Faltantes</th><th class="num">%</th>'
            f'<th class="num">Límite</th><th>Estado</th></tr></thead><tbody>{rows}</tbody></table>')


def _funnel_detail(target: str, funnel: dict) -> str:
    steps = ""
    for s in funnel["steps"]:
        name = _named(_e(STEP_NAMES.get(s["step"], s["step"])), s["step"])
        if s.get("status") == "not_verifiable":
            steps += (f'<tr data-step="{_e(s["step"])}"><td>{name}</td><td colspan="2"><span class="status warn">'
                      f'No verificable</span> falta {_e(s["missing_column"])}; FinBank debe añadirlo en '
                      f'{_e(funnel["table"])}_v2.</td></tr>')
            continue
        steps += (f'<tr data-step="{_e(s["step"])}"><td>{name}</td><td class="num">{format_count(s["rows"])}</td>'
                  f'<td class="num">{format_count(s["clients"])}</td></tr>')
    horizons = "".join(
        f'<tr data-horizon-row="{_e(label)}"><td>{_named(_plain(label), label)}</td>'
        f'<td class="num">{format_count(h["mature_clients"])}</td><td class="num">{format_count(h["immature_rows"])}</td>'
        f'<td class="num">{format_count(h["positive_clients"])}</td><td class="num">{format_pct(h["base_rate"])}</td></tr>'
        for label, h in funnel["horizons"].items())
    name = _plain(target)
    return (f'<table class="data"><caption>Pasos del etiquetado · {name}</caption><thead><tr><th>Paso</th>'
            f'<th class="num">Filas</th><th class="num">Clientes</th></tr></thead><tbody>{steps}</tbody></table>'
            f'<table class="data"><caption>Por horizonte · {name}</caption><thead><tr><th>Etiqueta</th>'
            '<th class="num">Clientes maduros</th><th class="num">Filas inmaduras</th><th class="num">Clientes con evento'
            f'</th><th class="num">Tasa base</th></tr></thead><tbody>{horizons}</tbody></table>')


def _data_view(data: dict) -> str:
    quality = data["quality"]
    status, _ = _data_status(data["gates"]["gate1"])
    waivers = "".join(_waiver_card(w, data) for w in quality["waivers"])
    funnels = "".join(_funnel_card(t, f) for t, f in quality["labeling_funnel"].items())
    detail = (f'<details class="technical" id="data-technical"><summary>Detalle técnico</summary>'
              f'<p>Gate 1: {_status(status)}</p>'
              f'{_gate1_table(data["gates"]["gate1"], DATA_TABLES, "Gate 1 por tabla y regla")}{_missing_detail(data)}'
              + "".join(_funnel_detail(t, f) for t, f in quality["labeling_funnel"].items()) + '</details>')
    return (f'<section class="view" id="datos"><h2 class="view-title">{dict(TABS)["datos"]}</h2>'
            f'<p class="q">{DATA_QUESTION}</p><p class="answer" id="data-answer">{_data_answer(data)}</p>'
            f'{_table_cards(data)}<div class="grid two">{_missing_card(data)}{waivers}</div>'
            f'<div class="stack">{funnels}</div>{detail}</section>')


# --- traceability: where does every figure come from? ---------------------------------------------

TRACE_QUESTION = "¿De dónde sale cada cifra?"
TRACED_FIGURE = "exposure.delinquency.observed_cop_m"
LOG_STRIP = {
    "OK": ("ok", "La cadena del registro de linaje está íntegra: ninguna corrida anterior fue alterada."),
    "TAMPERED": ("bad", "El registro de linaje fue alterado: no confíe en estas cifras hasta revisarlo."),
    "NOT_CHECKED": ("warn", "El registro no se verificó: esta es la primera corrida anotada en él."),
}
FIGURE_GROUPS = (("delinquency", "Mora temprana"), ("churn", "Fuga de clientes preferenciales"),
                 ("management", "Gestión del proyecto"), ("other", "Otras cifras"))
METRIC_NAMES = {"observed_cop_m": "Exposición observada", "net_value_at_k_cop_m": "Valor neto con la capacidad actual",
                "capture_at_k": "Captura con la capacidad actual", "difference_vs_baseline_cop_m": "Ventaja sobre la regla actual",
                "ci_low_vs_baseline_cop_m": "Ventaja: límite inferior del intervalo",
                "ci_high_vs_baseline_cop_m": "Ventaja: límite superior del intervalo",
                "breakeven_effectiveness": "Efectividad mínima para compensar",
                "pv_cop_m": "Valor planeado (PV)", "ev_cop_m": "Valor ganado (EV)", "ac_cop_m": "Costo real (AC)",
                "spi": "Índice de cronograma (SPI)", "cpi": "Índice de costo (CPI)", "eac_cop_m": "Estimado al cierre (EAC)",
                "bac_cop_m": "Presupuesto (BAC)", "ceiling_cop_m": "Techo del charter"}


def _figure_name(figure_id: str) -> tuple[str, str]:
    """(group, reader's name) of a registered figure, from the parts of its id."""
    family, *rest = figure_id.split(".")
    metric = METRIC_NAMES.get(rest[-1], rest[-1]) if rest else figure_id
    if family == "exposure" and rest:
        return rest[0], metric
    if family == "models" and len(rest) == 3:
        group = "delinquency" if rest[0].startswith("delinquency") else "churn" if rest[0].startswith("churn") else "other"
        return group, f"{PLAIN_NAMES.get(rest[0], rest[0])} · {PLAIN_NAMES.get(rest[1], rest[1])} · {metric}"
    if family == "management":
        return "management", metric
    return "other", metric


def _trace_answer(data: dict) -> str:
    manifest = data["lineage"]["manifest"]
    n = len(data["lineage"]["figures"])
    chain = {"OK": "y la cadena del registro está íntegra", "TAMPERED": "pero el registro fue alterado",
             "NOT_CHECKED": "y es la primera corrida del registro"}[data["lineage"]["log_status"]]
    return (f'Las {_plural(n, "cifra rastreable", "cifras rastreables")} de esta corrida salen de '
            f'{_plural(len(manifest["sources"]), "fuente", "fuentes")}, pasan por 3 controles y quedan en '
            f'{_plural(len(manifest["outputs"]), "archivo", "archivos")} de salida con su huella; cada una se puede '
            f'seguir hasta su archivo, script y commit, {chain}.')


def _flow(data: dict) -> str:
    manifest = data["lineage"]["manifest"]
    steps = (("sources", "db", len(manifest["sources"]), "Fuentes", "datos, configuración y registros de PCM"),
             ("controls", "shield", 3, "Controles", "Gate 1 datos, Gate 2 fichas, Gate 3 cifras"),
             ("outputs", "file", len(manifest["outputs"]), "Salidas", "archivos con su huella digital"),
             ("figures", "check", len(data["lineage"]["figures"]), "Cifras rastreables", "verificadas por el Gate 3"))
    items = "".join(f'<li data-flow="{key}"><span class="bubble blue">{_icon(icon)}</span><div><strong>'
                    f'{format_count(count)}</strong><span class="flow-name">{name}</span><span class="flow-sub">{sub}'
                    '</span></div></li>' for key, icon, count, name, sub in steps)
    return f'<ol class="flow" id="trace-flow">{items}</ol>'


def _log_strip(lineage: dict) -> str:
    cls, text = LOG_STRIP[lineage["log_status"]]
    return f'<div class="strip {cls}" id="log-status" role="status">{_icon(PILL_ICONS[cls])}<span>{text}</span></div>'


def _trace_story(data: dict) -> str:
    figure = next((f for f in data["lineage"]["figures"] if f["figure_id"] == TRACED_FIGURE), None)
    if figure is None:
        return '<div class="card" id="trace-story"><p class="plain">La exposición de mora no está registrada en esta corrida.</p></div>'
    manifest, meta, gate3 = data["lineage"]["manifest"], data["meta"], data["gates"]["gate3"]
    sources = {s["name"]: s for s in manifest["sources"]}
    source = next((sources[n] for n in _figure_sources(TRACED_FIGURE) if n in sources), None)
    output = next((o for o in manifest["outputs"] if o["file"] == figure["file"]), None)
    if gate3["status"] == "NOT_RUN":
        check = _pill("warn", "El Gate 3 no corrió: la cifra no se verificó")
    elif any(m["figure_id"] == TRACED_FIGURE for m in gate3["mismatches"]):
        check = _pill("bad", "El Gate 3 la recalculó desde el archivo y NO coincide")
    else:
        check = _pill("ok", "El Gate 3 la recalculó desde el archivo y coincide")
    dirty = " (con cambios sin commit: no es una corrida oficial)" if meta["commit"].endswith("-dirty") else ""
    steps = (
        ("file", "Archivo de origen", "Los datos de la cartera de mora entran en este archivo"
         + (f', con {_plural(source["rows"], "fila", "filas")}' if source and source["rows"] else ""),
         (f'<code>{_e(source["file"])}</code> · huella {_short(source["sha256"])}' if source else DASH)),
        ("script", "Script", "Suma la exposición observada y la concilia con la cifra del banco",
         f'<code>{_e(figure["script"])}</code>'),
        ("output", "Archivo de salida", "El resultado queda escrito aquí, en esta ruta",
         f'<code>{_e(figure["file"])}</code> · <code>{_e(figure["path"])}</code> · huella '
         f'{_short(output["sha256"] if output else None)}'),
        ("commit", "Commit", f"La versión exacta del código que la calculó{dirty}",
         f'<code title="{_e(meta["commit"])}">{_e(meta["commit"][:8])}</code>'),
        ("check", "Verificación", "Se comprueba en cada corrida", check),
    )
    items = "".join(f'<li data-trace-step="{key}"><span class="step-n">{n}</span><div><p class="step-title">{title}</p>'
                    f'<p class="step-text">{text}</p><p class="step-value">{value}</p></div></li>'
                    for n, (key, title, text, value) in enumerate(steps, start=1))
    return (f'<div class="card" id="trace-story"><h3>La exposición de {_plain("delinquency").lower()}, '
            f'{format_cop_m(figure["value"])}, se rastrea en cinco pasos</h3><ol class="steps">{items}</ol></div>')


def _finder(data: dict) -> str:
    outputs = {o["file"]: o["sha256"] for o in data["lineage"]["manifest"]["outputs"]}
    groups: dict = {}
    for f in data["lineage"]["figures"]:
        group, name = _figure_name(f["figure_id"])
        groups.setdefault(group if group in dict(FIGURE_GROUPS) else "other", []).append((name, f))
    tables = ""
    for key, caption in FIGURE_GROUPS:
        rows = "".join(
            f'<tr data-figure-row="{_e(f["figure_id"])}"><td>{_named(_e(name), f["figure_id"])}</td>'
            f'<td class="num">{_e(format_figure(f["value"], f["unit"], "es"))}</td>'
            f'<td><code>{_e(f["file"])}</code> {_short(outputs.get(f["file"]))}</td></tr>'
            for name, f in groups.get(key, []))
        if rows:
            tables += (f'<table class="data zebra"><caption>{caption}</caption><thead><tr><th>Cifra</th>'
                       f'<th class="num">Valor</th><th>Archivo y huella</th></tr></thead><tbody>{rows}</tbody></table>')
    n = len(data["lineage"]["figures"])
    return (f'<details class="finder" id="figure-finder"><summary>Buscar una cifra · '
            f'{_plural(n, "cifra rastreable", "cifras rastreables")}</summary><p class="note">Abra la lista y use la '
            f'búsqueda del navegador (Ctrl+F) con el nombre o el valor.</p>{tables}</details>')


def _files_table(entries: list, caption: str, with_name: bool) -> str:
    head = ("<th>Fuente</th>" if with_name else "") + '<th>Archivo</th><th class="num">Filas</th><th>sha256</th>'
    rows = "".join(
        "<tr>" + (f'<td>{_e(e["name"])}</td>' if with_name else "")
        + f'<td><code>{_e(e["file"])}</code></td><td class="num">{format_count(e["rows"])}</td>'
          f'<td><code>{_e(e["sha256"])}</code></td></tr>'
        for e in entries)
    return (f'<table class="data"><caption>{caption}</caption><thead><tr>{head}</tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def _figures_paths(data: dict) -> str:
    rows = "".join(f'<tr><td><code>{_e(f["figure_id"])}</code></td><td><code>{_e(f["path"])}</code></td>'
                   f'<td><code>{_e(f["script"])}</code></td></tr>' for f in data["lineage"]["figures"])
    return ('<table class="data"><caption>Ruta de cada cifra (la que lee el Gate 3)</caption><thead><tr><th>Cifra</th>'
            f'<th>Ruta en el archivo</th><th>Script</th></tr></thead><tbody>{rows}</tbody></table>')


def _trace_view(data: dict) -> str:
    lineage = data["lineage"]
    manifest = lineage["manifest"]
    head = manifest["lineage_head_sha256"]
    run = (f'<dl class="kv"><dt>Estado del registro</dt><dd>{_status(lineage["log_status"])}</dd>'
           f'<dt>Corrida</dt><dd><code>{_e(manifest["run_id"])}</code></dd>'
           f'<dt>Abierta</dt><dd>{_e(manifest["created_at"])}</dd><dt>Exportada</dt><dd>{_e(manifest["closed_at"])}</dd>'
           f'<dt>Ancla en el registro</dt><dd>{f"<code>{_e(head)}</code>" if head else "primera entrada del registro"}</dd>'
           f'<dt>Scores</dt><dd><code>{_e(manifest["scores_sha256"])}</code></dd></dl>')
    detail = (f'<details class="technical" id="trace-technical"><summary>Detalle técnico</summary>{run}'
              f'<p class="note" id="manifest-snapshot">{SNAPSHOT_NOTE}</p>'
              f'{_files_table(manifest["sources"], "Fuentes de la corrida", True)}'
              f'{_files_table(manifest["outputs"], "Salidas de la corrida", False)}{_figures_paths(data)}</details>')
    return (f'<section class="view" id="trazabilidad"><h2 class="view-title">{dict(TABS)["trazabilidad"]}</h2>'
            f'<p class="q">{TRACE_QUESTION}</p><p class="answer" id="trace-answer">{_trace_answer(data)}</p>'
            f'{_flow(data)}{_log_strip(lineage)}{_trace_story(data)}{_finder(data)}{detail}</section>')


# --- stress view: curve and simulator ----------------------------------------------------------



def _by_label(data: dict) -> dict:
    labels: dict = {}
    for e in data["models"]["evaluations"]:
        if e["status"] == "evaluated":
            labels.setdefault(e["label"], []).append(e)
    return {label: sorted(rows, key=lambda e: e["model_id"]) for label, rows in labels.items()}


def _rule(data: dict) -> str:
    return next((e["vs_baseline"]["baseline_model"] for e in data["models"]["evaluations"]
                 if e["status"] == "evaluated" and e.get("vs_baseline")), "baseline_rule")


def _capacity_share(data: dict) -> float:
    values = {k: v for item in data["assumptions"] for k, v in item["value"].items()}
    return values["value.default_capacity_share"]


def _k_definition(key: str, label_ks: list, data: dict) -> str:
    """«¿Qué es K?» with the k_applied of each label: the share is applied per label and snapped to the curve."""
    counts = _and([f'<span data-k="{_e(label)}">{format_count(k)}</span> en {_plain(label)}' for label, k in label_ks])
    return (f'<p class="k-def" data-k-definition="{_e(key)}"><strong>¿Qué es K?</strong> K es la capacidad de hoy: '
            f'los clientes que el equipo de FinBank alcanza a contactar, el {format_pct(_capacity_share(data), decimals=0)} de '
            f'los clientes evaluados (supuesto de diseño), ajustado a los puntos de la curva: {counts}. Todos los '
            'modelos se comparan contactando esa misma cantidad. K* es el mejor número de contactos: el que daría '
            'más valor neto si no hubiera límite de capacidad.</p>')


def curve_svg(label: str, evaluations: list, capacity_k: float | None = None) -> str:
    """Net value against the clients contacted for each model, the random line and the best number of contacts.
    Drawn with the assumptions of the acta (the values the evaluator published)."""
    width, height, left, right, top, bottom = 960, 340, 100, 16, 16, 40   # left fits "COP -1.358 M"
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
    for e in evaluations:
        points = " ".join(f"{x(p['k']):.1f},{y(p['net_value_cop_m']):.1f}" for p in e["curve"])
        parts.append(f'<polyline class="series m-{_e(e["model_id"])}" data-series="{_e(e["model_id"])}" points="{points}"/>')
        star = e["k_star"]
        parts.append(f'<circle class="kstar m-{_e(e["model_id"])}" data-kstar="{_e(e["model_id"])}" cx="{x(star["k"]):.1f}" '
                     f'cy="{y(star["net_value_cop_m"]):.1f}" r="4"><title>Mejor número de contactos, {_plain(e["model_id"])}: '
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
              'Clientes contactados</text>']
    title = f"Valor neto en COP según clientes contactados · {PLAIN_NAMES.get(label, label)}"
    plot_h = height - top - bottom
    return (f'<svg class="curve" data-curve="{_e(label)}" data-x0="{left}" data-xscale="{xscale!r}" '
            f'data-top="{top}" data-plot-h="{plot_h}" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="{_e(title)}"><title>{_e(title)}</title>{"".join(parts)}</svg>')


def _acta(data: dict) -> dict:
    """The value assumptions recorded in the acta, in the simulator's shape."""
    values = {k: v for item in data["assumptions"] for k, v in item["value"].items()}
    return {"capacity_share": values["value.default_capacity_share"],
            "action_effectiveness": values["value.action_effectiveness"],
            "loss_given_event": values["value.loss_given_event"],
            "cost_per_contact_cop": values["value.cost_per_contact_cop"]}


def _phrase(model_id: str, rule: str) -> str:
    name = PLAIN_NAMES.get(model_id, model_id)
    return f"la {name}" if model_id == rule else name


def simulator_data(data: dict) -> dict:
    """What simulator.js needs: the acta's assumptions and, per label and model, the published
    curve plus the evaluator's own numbers for the browser self-check."""
    rule = _rule(data)
    return {
        "defaults": _acta(data),
        "rule": rule,
        "random_name": PLAIN_NAMES["random"],
        "labels": {label: {"target": rows[0]["target"], "name": PLAIN_NAMES.get(label, label), "models": [{
            "model_id": e["model_id"], "name": PLAIN_NAMES.get(e["model_id"], e["model_id"]),
            "phrase": _phrase(e["model_id"], rule),
            "n_clients": e["n_clients"],
            "event_exposure_cop_m": e["event_exposure_cop_m"], "k_applied": e["k_applied"],
            "k_star_k": e["k_star"]["k"], "at_k_net_value_cop_m": e["at_k"]["net_value_cop_m"],
            "random_net_value_cop_m": e["random_at_k"]["net_value_cop_m"],
            "curve": [{"k": p["k"], "captured_cop_m": p["captured_cop_m"], "net_value_cop_m": p["net_value_cop_m"]}
                      for p in e["curve"]]} for e in rows]}
            for label, rows in _by_label(data).items()},
    }


def _bar_layout(options: list, best: str) -> dict:
    """Bars of net value from a zero line, highest first; mirrors bars() in simulator.js."""
    nets = [o["net"] for o in options]
    low, high = min([0.0] + nets), max([0.0] + nets)
    span = (high - low) or 1.0
    zero = (0.0 - low) / span * 100
    rows = []
    for o in sorted(options, key=lambda o: -o["net"]):
        pos = (o["net"] - low) / span * 100
        tone = "neg" if o["net"] < 0 else "best" if o["id"] == best else "other"
        rows.append({"id": o["id"], "name": o["name"], "net": o["net"], "tone": tone,
                     "left": min(zero, pos), "width": abs(pos - zero)})
    return {"zero": zero, "rows": rows}


def _capacity_texts(k: float, k_today: float, scenario: bool) -> dict:
    """«capacidad de hoy» at the acta's capacity; «capacidad del escenario: N clientes (hoy: M)» away from it."""
    if not scenario:
        return {"barsTitle": f"Valor neto llamando a {format_count(k)} clientes (capacidad de hoy)",
                "scope": f"Con la capacidad de hoy: {format_count(k)} clientes",
                "capacityHeader": "Capacidad de hoy (clientes)", "netHeader": "Valor neto con la capacidad de hoy",
                "legendCapacity": "Capacidad de hoy",
                "belowLead": f"Con la capacidad de hoy ({format_count(k)} clientes) quedan"}
    where = f"capacidad del escenario: {format_count(k)} clientes (hoy: {format_count(k_today)})"
    return {"barsTitle": f"Valor neto con la {where}", "scope": f"Con la {where}",
            "capacityHeader": f"Capacidad del escenario (clientes; hoy: {format_count(k_today)})",
            "netHeader": "Valor neto con la capacidad del escenario", "legendCapacity": "Capacidad del escenario",
            "belowLead": f"Con la {where}, quedan"}


def _story_texts(label_name: str, k: float, a: dict, best: dict, rule: dict | None, rule_id: str,
                 recovered: float, cost: float, breakeven, below: list, k_today: float, scenario: bool) -> dict:
    """Every sentence of the view for one label; mirrors storyTexts() in simulator.js word by word."""
    phrase = _phrase(best["model_id"], rule_id)
    capacity = _capacity_texts(k, k_today, scenario)
    if best["net"] < 0:
        answer = (f"Con su equipo de hoy, llamar no compensa el costo en {label_name}: la mejor opción, "
                  f"{phrase}, deja {format_cop_m(best['net'])}.")
    elif rule is None or rule is best:
        answer = f"Con su equipo de hoy, {phrase} deja {format_cop_m(best['net'])} netos en {label_name}."
    else:
        answer = (f"Con su equipo de hoy, {phrase} deja {format_cop_m(best['net'])} netos en {label_name}; "
                  f"{_phrase(rule_id, rule_id)}, {format_cop_m(rule['net'])}.")
    effectiveness = format_decimal(a["action_effectiveness"] * 100, 0)
    if breakeven is None:
        threshold = f"Con {phrase}, en la lista no hay plata en riesgo: llamar no compensa con ninguna efectividad."
    else:
        margin = (a["action_effectiveness"] - breakeven) * 100
        needed = ("aunque se recupere menos de 1 de cada 100" if breakeven * 100 < 1
                  else f"mientras se recuperen al menos {format_decimal(breakeven * 100, 1)} de cada 100")
        threshold = (f"Con {phrase}, llamar compensa {needed}. Hoy suponemos {effectiveness}: "
                     + (f"margen de {format_decimal(margin, 1)} puntos." if margin >= 0
                        else f"faltan {format_decimal(-margin, 1)} puntos."))
    below_text = ""
    if below:
        below_text = (f"{capacity.pop('belowLead')} por debajo de su mejor número "
                      "de contactos: " + _and([f"{name} ({format_count(star)})" for name, star in below]) + ".")
    capacity.pop("belowLead", None)
    return {**capacity, "answer": answer, "k": format_count(k), "capacity": f"{format_count(k)} clientes",
            "who": f"{format_count(best['k'])} clientes", "whoNote": f"los de mayor riesgo según {phrase}",
            "captured": format_cop_m(best["captured"]), "recovered": format_cop_m(recovered),
            "recoveredNote": f"se recuperan {effectiveness} de cada 100",
            "cost": format_cop_m(cost),
            "costNote": f"{format_count(best['k'])} × COP {format_count(a['cost_per_contact_cop'])}",
            "net": f"Quedan {format_cop_m(best['net'])} netos", "threshold": threshold, "below": below_text}


def stress_story(label: str, evaluations: list, data: dict) -> dict:
    """What the view says for one label with the acta's assumptions, from the evaluator's numbers.
    simulator.js computes the same story in the browser; the parity tests compare both."""
    a, rule_id = _acta(data), _rule(data)
    values = {"value": a}
    options, best, rule = [], None, None
    for e in evaluations:
        option = {"id": e["model_id"], "model_id": e["model_id"], "name": PLAIN_NAMES.get(e["model_id"], e["model_id"]),
                  "net": e["at_k"]["net_value_cop_m"], "captured": e["at_k"]["captured_cop_m"],
                  "breakeven": e["breakeven_effectiveness"], "k": e["k_applied"]}
        options.append(option)
        if best is None or option["net"] > best["net"]:
            best = option
        if e["model_id"] == rule_id:
            rule = option
    k = evaluations[0]["k_applied"]
    options.append({"id": "random", "name": PLAIN_NAMES["random"], "net": evaluations[0]["random_at_k"]["net_value_cop_m"]})
    below = [(PLAIN_NAMES.get(e["model_id"], e["model_id"]), e["k_star"]["k"]) for e in evaluations
             if e["k_star"]["k"] > e["k_applied"]]
    texts = _story_texts(PLAIN_NAMES.get(label, label), k, a, best, rule, rule_id,
                         _gain_cop_m(best["captured"], values), _contact_cost_cop_m(best["k"], values), best["breakeven"],
                         below, k, scenario=False)
    return {"best": best["id"], "breakeven": best["breakeven"], "bars": _bar_layout(options, best["id"]),
            "texts": texts}


STRESS_QUESTION = ("Con el equipo de hoy, ¿cuánta plata deja cada opción, y qué tan equivocados pueden estar "
                   "los supuestos antes de que deje de convenir?")
SCENARIO_NOTE = "esto es un escenario y no cambia el dictamen."


def _verdict_line(target: str, data: dict) -> str:
    decision = next((d for d in data["models"]["decisions"] if d["target"] == target), None)
    if decision is None:
        text = "sin dictamen"
    else:
        verdict, _ = VERDICTS[decision["verdict"]]
        tag, _ = DECISION_TAGS[decision["reason_code"]]
        model = (f" ({_plain(decision['model_id'])})" if decision["verdict"] == "authorized_for_shadow_deployment"
                 and decision["model_id"] else "")
        text = f"{verdict}{model}, {tag[0].lower() + tag[1:]}"
    return (f'<p class="verdict-line" data-verdict-line="{_e(target)}">Dictamen oficial en {_plain(target)}: '
            f'{text}; {SCENARIO_NOTE}</p>')


def _t(label: str, key: str, texts: dict, tag: str = "span", cls: str = "") -> str:
    attr = f' class="{cls}"' if cls else ""
    return f'<{tag}{attr} data-sim-text="{_e(label)}.{key}">{_e(texts[key])}</{tag}>'


def _bars_html(label: str, bars: dict) -> str:
    rows = ""
    for n, r in enumerate(bars["rows"]):
        rows += (f'<div class="bar-row tone-{r["tone"]}" data-bar="{_e(label)}.{_e(r["id"])}" style="order:{n}">'
                 f'<span class="bar-name">{_e(r["name"])}</span><span class="bar-track">'
                 f'<span class="bar-zero" style="left:{bars["zero"]:.2f}%"></span>'
                 f'<span class="bar" style="left:{r["left"]:.2f}%;width:{r["width"]:.2f}%"></span></span>'
                 f'<span class="bar-value" data-bar-value="{_e(label)}.{_e(r["id"])}">{format_cop_m(r["net"])}</span></div>')
    return f'<div class="bars" data-sim-bars="{_e(label)}">{rows}</div>'


def _bridge(label: str, texts: dict) -> str:
    def step(title, key, note):
        note_html = (_t(label, note, texts, "p", "label-sm") if note
                     else '<p class="label-sm">lo que está en riesgo entre esos clientes</p>')
        return f'<article class="bridge-step"><h4>{title}</h4>{_t(label, key, texts, "p", "value")}{note_html}</article>'
    return (f'<div class="card"><h3>¿De dónde sale esa cifra?</h3>{_t(label, "scope", texts, "p", "label-sm")}'
            f'<div class="bridge" data-sim-bridge="{_e(label)}">'
            + step("A quién llamar", "who", "whoNote")
            + step("Plata en riesgo en la lista", "captured", None)
            + step("Se recupera", "recovered", "recoveredNote")
            + step("Menos el costo de llamar", "cost", "costNote")
            + f'</div>{_t(label, "net", texts, "p", "bridge-net")}</div>')


def _legend(label: str, evaluations: list, texts: dict) -> str:
    return _model_legend(evaluations, '<li><span class="swatch random"></span>Al azar</li>',
                         f'<li><span class="swatch capacity"></span>{_t(label, "legendCapacity", texts)}</li>',
                         '<li><span class="dot"></span>Mejor número de contactos</li>')


def _stress_table(label: str, evaluations: list, rule: str, texts: dict) -> str:
    rule_net = next((e["at_k"]["net_value_cop_m"] for e in evaluations if e["model_id"] == rule), None)
    rows = ""
    for e in evaluations:
        key = f'{label}.{e["model_id"]}'
        net = e["at_k"]["net_value_cop_m"]
        diff = DASH if e["model_id"] == rule or rule_net is None else format_cop_m(net - rule_net)
        rows += (f'<tr><td>{_plain(e["model_id"])}</td>'
                 f'<td data-sim-kstar="{_e(key)}">{format_count(e["k_star"]["k"])}</td>'
                 f'<td data-sim-kapplied="{_e(key)}">{format_count(e["k_applied"])}</td>'
                 f'<td data-sim-net="{_e(key)}">{format_cop_m(net)}</td>'
                 f'<td data-sim-diff="{_e(key)}">{diff}</td></tr>')
    random_net = evaluations[0]["random_at_k"]["net_value_cop_m"]
    rows += (f'<tr class="random"><td>{_plain("random")}</td><td>{DASH}</td><td>{DASH}</td>'
             f'<td data-sim-net="{_e(label)}.random">{format_cop_m(random_net)}</td><td>{DASH}</td></tr>')
    return ('<table class="compare"><thead><tr><th>Modelo</th><th>Mejor número de contactos</th>'
            f'{_t(label, "capacityHeader", texts, "th")}'
            f'{_t(label, "netHeader", texts, "th")}<th>Diferencia vs {_plain(rule)}<br><span class="label-sm">'
            'estimación puntual, sin intervalo</span></th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def _stress_panel(label: str, evaluations: list, data: dict, rule: str) -> str:
    story = stress_story(label, evaluations, data)
    texts = story["texts"]
    below = _t(label, "below", texts, "p", "note")
    return (f'<div class="stress-panel" data-stress-for="{_e(label)}">'
            f'{_t(label, "answer", texts, "p", "answer")}{_verdict_line(evaluations[0]["target"], data)}'
            f'<div class="card">{_t(label, "barsTitle", texts, "h3")}'
            f'{_bars_html(label, story["bars"])}'
            '<p class="note">Azul: la opción que más deja. Gris: las demás. Rojo: pierden plata.</p></div>'
            f'{_bridge(label, texts)}'
            f'{_t(label, "threshold", texts, "p", "threshold")}'
            f'<details class="technical"><summary>Detalle técnico</summary>'
            f'{_k_definition(label, [(label, evaluations[0]["k_applied"])], data)}'
            f'{curve_svg(label, evaluations, evaluations[0]["k_applied"])}{_legend(label, evaluations, texts)}'
            f'{_stress_table(label, evaluations, rule, texts)}{below}</details>'
            '</div><!-- /stress-panel -->')


def _stress_view(data: dict) -> str:
    sim = simulator_data(data)
    d = sim["defaults"]
    script = (ASSETS_DIR / "simulator.js").read_text(encoding="utf-8")
    payload = json.dumps(sim, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    labels = _by_label(data)
    if not labels:
        return (f'<section class="view" id="estres"><h2 class="view-title">{dict(TABS)["estres"]}</h2>'
                f'<p class="q">{STRESS_QUESTION}</p>'
                '<div class="pending">Sin modelos evaluados: no hay escenarios que simular.</div></section>')
    inputs, capacity, panels, rules = "", "", "", ""
    for n, (label, evaluations) in enumerate(labels.items()):
        checked = " checked" if n == 0 else ""
        inputs += (f'<input type="radio" name="stress-label" id="stress-{_e(label)}"{checked}>'
                   f'<label for="stress-{_e(label)}">{_plain(label)}</label>')
        capacity += (f'<span class="for-label" data-sim-capacity-for="{_e(label)}">'
                     f'{format_count(evaluations[0]["k_applied"])} clientes</span>')
        panels += _stress_panel(label, evaluations, data, sim["rule"])
        rules += (f'#stress-{label}:checked ~ .stress-panel[data-stress-for="{label}"] {{ display: block; }} '
                  f'#stress-{label}:checked ~ form [data-sim-capacity-for="{label}"] {{ display: inline; }} ')
    effectiveness = round(d["action_effectiveness"] * 100)
    return (
        f'<section class="view" id="estres"><h2 class="view-title">{dict(TABS)["estres"]}</h2>'
        f'<p class="q">{STRESS_QUESTION}</p>'
        f'<style>.stress-switch .stress-panel, .stress-switch .for-label {{ display: none; }} {rules}</style>'
        f'<div class="stress-switch">{inputs}'
        '<form class="card sim-controls" id="sim-controls" onsubmit="return false">'
        f'<label>Capacidad de gestión <output id="sim-capacity-out">{capacity} · '
        f'<span id="sim-capacity-share">{format_pct(d["capacity_share"], decimals=0)}</span> de los clientes</output>'
        f'<input type="range" id="sim-capacity" min="1" max="100" step="1" value="{round(d["capacity_share"] * 100)}"></label>'
        f'<label>Efectividad de la acción <output id="sim-effectiveness-out">se recuperan {effectiveness} de cada 100 '
        'en riesgo contactados</output>'
        f'<input type="range" id="sim-effectiveness" min="0" max="100" step="5" value="{effectiveness}"></label>'
        f'<label>Costo por contacto <output id="sim-cost-out">COP {format_count(d["cost_per_contact_cop"])}</output>'
        f'<input type="range" id="sim-cost" min="0" max="200000" step="1000" value="{d["cost_per_contact_cop"]}"></label>'
        '<button type="button" id="sim-reset">Restablecer supuestos</button>'
        f'<p class="note">Pérdida por evento fija en {format_pct(d["loss_given_event"])} de la exposición. '
        'Sin JavaScript se muestran los valores del acta.</p></form>'
        '<p class="note" id="sim-status" role="status" hidden></p>'
        f'{panels}</div>'
        f'<script type="application/json" id="sim-data">{payload}</script>'
        f'<script>{script}</script></section>'
    )


# --- models view: which model ranks best, and is the evidence enough? ---------------------------

MODELS_QUESTION = "¿Qué modelo ordena mejor y alcanza la evidencia?"
DECISION_TAGS = {"authorized": ("Supera la regla", "ok"), "insufficient_evidence": ("Evidencia insuficiente", "warn"),
                 "does_not_beat_baseline": ("No supera la regla", "bad"),
                 "no_baseline": ("Sin regla base comparable", "warn"), "no_candidate": ("Sin modelo candidato", "warn")}
CARD_DECISIONS = {"ADMITTED": ("Admitida", "ok"), "REJECTED": ("Rechazada", "bad"), "SKIPPED": ("Omitida", "warn")}
NOT_EVALUATED = {"incomplete_scores": "scores incompletos"}
DELINQUENCY_RULE = ("Mora exige ganar a 30 y a 60 días: se autoriza solo si todo el intervalo supera el margen "
                    "en ambos horizontes.")
SLICES_PENDING = ("Rebanadas: pendiente. La primera será la de clientes sin antigüedad registrada "
                  "(riesgo R-01, excepción W-01), evaluada aparte y sin imputar.")
SIMULATED_NOTE = ("Scores simulados: no son modelos entrenados. El sistema evalúa en COP cualquier modelo que "
                  "FinBank entrene; estos sirven para mostrar cómo.")
TICK_STEPS = (10, 50, 100, 500, 1000, 5000)       # round steps of the interval axis, in COP millions
MAX_TICKS = 8
QUARTERS = (0, 25, 50, 75, 100)
METRIC_GROUPS = (("¿Encuentra la plata?", ("Captura", "Capturado", "Lift")),
                 ("¿Acierta?", ("Precisión", "Recall", "PR-AUC")),
                 ("¿Son confiables sus probabilidades?", ("Brier",)),
                 ("¿Cuánto vale?", ("Valor neto en K", "K*", "Valor neto en K*", "Efectividad mínima")))


def _f(value: float) -> str:
    return f"{value:.3f}"


def _compared(target: str, data: dict) -> list:
    return sorted((e for e in data["models"]["evaluations"] if e["target"] == target and e["status"] == "evaluated"
                   and e["vs_baseline"]), key=lambda e: (e["model_id"], e["label"]))


def _and(items: list) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " y " + items[-1]


def _target_finding(decision: dict, data: dict) -> str:
    """What the comparisons of one target say, in a clause; generated from the JSON."""
    target = _plain(decision["target"])
    rows = _compared(decision["target"], data)
    if not rows:
        return f"en {target} no hay comparación contra la Regla actual"
    beats = {}
    for e in rows:
        beats.setdefault(e["model_id"], {"yes": [], "no": []})["yes" if e["vs_baseline"]["outcome"] == "beats"
                                                              else "no"].append(_plain(e["label"]))
    winners = [(m, r) for m, r in beats.items() if r["yes"]]
    if winners:
        clauses = []
        for model_id, r in winners:
            clause = f"{_plain(model_id)} la supera en {_and(r['yes'])}"
            if r["no"]:
                clause += f", pero no en {_and(r['no'])}"
            clauses.append(clause)
        return f"en {target}, " + "; ".join(clauses)
    if all(e["vs_baseline"]["outcome"] == "insufficient_evidence" for e in rows):
        return f"en {target}, todos los intervalos cruzan el cero"
    return f"en {target}, ningún modelo supera la Regla actual"


def _models_answer(data: dict) -> str:
    decisions = data["models"]["decisions"]
    if not decisions:
        return "Todavía no hay dictamen sobre los modelos."
    authorized = _authorized_decisions(data)
    rest = [d for d in decisions if d not in authorized]
    findings = [_target_finding(d, data) for d in rest]
    if authorized:
        lead = "; ".join(f"en {_plain(d['target'])}, {_plain(d['model_id'])} está autorizado a despliegue en sombra"
                         for d in authorized)
        lead = lead[0].upper() + lead[1:]
        return lead + (f"; {'; '.join(findings)}." if findings else ".")
    return ("Ningún modelo tiene todavía evidencia suficiente para reemplazar la Regla actual: "
            + "; ".join(findings) + ".")


def _verdict_cards(data: dict) -> str:
    cards = ""
    for d in data["models"]["decisions"]:
        text, tone = VERDICTS[d["verdict"]]
        tag, cls = DECISION_TAGS[d["reason_code"]]
        model = (f'<p class="kpi-sub">{_plain(d["model_id"])}, en sombra</p>'
                 if d["verdict"] == "authorized_for_shadow_deployment" and d["model_id"] else "")
        bubble = "green" if tone == "ok" else "amber"
        tag_attr = f' data-decision-tag="{_e(d["target"])}"'
        cards += (f'<article class="kpi" data-verdict="{_e(d["target"])}"><div class="kpi-top"><span class="bubble '
                  f'{bubble}">{_icon("scale")}</span><span class="kpi-label">{_plain(d["target"])}</span></div>'
                  f'<div class="kpi-value">{text}</div>{model}{_pill(cls, tag, attrs=tag_attr)}</article>')
    return f'<div class="kpis two" id="models-verdict">{cards}</div>'


def _nice_ticks(low: float, high: float) -> list[float]:
    """Round ticks (every 10, 50, 100, 500, ...) that cover [low, high] and zero, at most MAX_TICKS + 1."""
    low, high = min(low, 0.0), max(high, 0.0)
    for step in TICK_STEPS:
        first, last = math.floor(low / step) * step, math.ceil(high / step) * step
        if (last - first) / step <= MAX_TICKS:
            break
    if last == first:
        last = first + step
    return [float(first + i * step) for i in range(int(round((last - first) / step)) + 1)]


def ci_svg(target: str, rows: list) -> str:
    """Advantage over the rule with its paired interval, one panel per target with its own round scale."""
    width, left, right, top, row_h, bottom = 960, 230, 28, 48, 50, 64
    height = top + row_h * len(rows) + bottom
    vs0 = rows[0]["vs_baseline"]
    margin, level = vs0["margin_cop_m"], vs0["confidence_level"]
    ticks = _nice_ticks(min([margin] + [e["vs_baseline"]["ci_low_cop_m"] for e in rows]),
                        max([margin] + [e["vs_baseline"]["ci_high_cop_m"] for e in rows]))
    vmin, vmax = ticks[0], ticks[-1]
    scale = (width - left - right) / (vmax - vmin)
    x = lambda v: left + (v - vmin) * scale
    plot_top, plot_bottom = top - 10, height - bottom
    zero = x(0.0)
    parts = [f'<rect class="rule-better" x="{_f(x(vmin))}" y="{plot_top}" width="{_f(zero - x(vmin))}" '
             f'height="{plot_bottom - plot_top}"/>']
    for t in ticks:
        parts.append(f'<line class="grid" data-value="{t:g}" x1="{_f(x(t))}" y1="{plot_top}" x2="{_f(x(t))}" '
                     f'y2="{plot_bottom}"/><text class="tick" data-tick-value="{t:g}" x="{_f(x(t))}" '
                     f'y="{plot_bottom + 18}" text-anchor="middle">{format_count(t)}</text>')
    parts += [f'<line class="zero" x1="{_f(zero)}" y1="{plot_top}" x2="{_f(zero)}" y2="{plot_bottom}"/>',
              f'<text class="side" x="{_f(zero - 8)}" y="{top - 20}" text-anchor="end">← la regla actual es mejor</text>',
              f'<text class="side" x="{_f(zero + 8)}" y="{top - 20}">el modelo es mejor →</text>']
    if margin:
        parts.append(f'<line class="margin" x1="{_f(x(margin))}" y1="{plot_top}" x2="{_f(x(margin))}" y2="{plot_bottom}"/>')
    for i, e in enumerate(rows):
        vs = e["vs_baseline"]
        cy = top + row_h * i + row_h / 2 + 6
        _, cls = OUTCOMES[vs["outcome"]]
        name = f'{_plain(e["model_id"])} · {_plain(e["label"])}'
        point = x(vs["difference_cop_m"])
        parts.append(
            f'<g data-ci="{_e(e["label"])}.{_e(e["model_id"])}" class="{cls}">'
            f'<text class="row-label" x="{left - 14}" y="{cy + 4:.1f}" text-anchor="end">{name}</text>'
            f'<line class="ci-range" x1="{_f(x(vs["ci_low_cop_m"]))}" y1="{cy:.1f}" x2="{_f(x(vs["ci_high_cop_m"]))}" '
            f'y2="{cy:.1f}"/><circle class="ci-point" cx="{_f(point)}" cy="{cy:.1f}" r="6">'
            f'<title>{name}: {format_cop_m(vs["difference_cop_m"])}, entre {format_cop_m(vs["ci_low_cop_m"])} y '
            f'{format_cop_m(vs["ci_high_cop_m"])}</title></circle>'
            f'<text class="ci-value" x="{_f(point)}" y="{cy - 12:.1f}" text-anchor="middle">'
            f'{format_cop_m(vs["difference_cop_m"])}</text></g>')
    axis = (f"Ventaja sobre la regla actual (COP millones), intervalo de confianza al "
            f"{format_count(level * 100)} %")
    parts.append(f'<text class="axis-title" x="{(left + width - right) / 2:.0f}" y="{height - 10}" '
                 f'text-anchor="middle">{axis}</text>')
    title = f"{axis} · {PLAIN_NAMES.get(target, target)}"
    return (f'<svg class="ci" data-ci-target="{_e(target)}" data-vmin="{vmin!r}" data-vmax="{vmax!r}" '
            f'data-x0="{left}" data-xscale="{scale!r}" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="{_e(title)}"><title>{_e(title)}</title>{"".join(parts)}</svg>')


def _decision_card(decision: dict, data: dict) -> str:
    target = decision["target"]
    rows = _compared(target, data)
    rule = f'<p class="plain">{DELINQUENCY_RULE}</p>' if target == "delinquency" else ""
    label_ks = [(label, evaluations[0]["k_applied"]) for label, evaluations in _by_label(data).items()
                if evaluations[0]["target"] == target]
    k_def = _k_definition(target, label_ks, data) if label_ks else ""
    if rows:
        body = (ci_svg(target, rows)
                + _how("Cada línea es el rango de la ventaja del modelo sobre la Regla actual; el punto es la "
                       "estimación y la cifra encima, su valor, contactando la capacidad de hoy de cada horizonte.",
                       "Verde: todo el rango queda a la derecha del cero, el modelo supera a la regla. "
                       "Ámbar: el rango cruza el cero, la evidencia no alcanza.",
                       "Cada objetivo tiene su propia escala.")
                + f'<details class="figures"><summary>Ver las cifras</summary>{_comparisons(target, data)}</details>')
    else:
        body = (f'<p class="label-sm" id="ci-none-{_e(target)}">Sin comparación contra la Regla actual: '
                'no hay intervalo que dibujar.</p>'
                f'<details class="technical"><summary>Detalle técnico</summary><p>{_e(decision["reason"])}</p></details>')
    return (f'<div class="card" data-decision-card="{_e(target)}"><h3>{_plain(target)}</h3>{rule}{k_def}{body}</div>')


def _capture_title(label: str, evaluations: list) -> str:
    best = max(evaluations, key=lambda e: e["at_k"]["capture"])
    title = (f'{_plain(label)}: llamando a {format_count(best["k_applied"])} clientes (capacidad de hoy), '
             f'{_plain(best["model_id"])} encuentra el '
             f'{format_pct(best["at_k"]["capture"])} de la exposición en riesgo')
    rule = next((e for e in evaluations if e["model_id"] == "baseline_rule"), None)
    if rule and rule is not best:
        title += f'; la {_plain("baseline_rule")}, el {format_pct(rule["at_k"]["capture"])}'
    return title + "."


def capture_svg(label: str, evaluations: list) -> str:
    """Share of the at-risk exposure found against the share of clients contacted; needs no assumption."""
    width, height, left, right, top, bottom = 960, 400, 64, 24, 30, 58
    w, h = width - left - right, height - top - bottom
    x0, y0 = left, top + h
    n = evaluations[0]["n_clients"]
    px = lambda k: x0 + w * k / n
    py = lambda capture: y0 - h * capture
    parts = []
    for q in QUARTERS:
        parts += [f'<line class="grid" data-axis="x" data-value="{q}" x1="{_f(x0 + w * q / 100)}" y1="{top}" '
                  f'x2="{_f(x0 + w * q / 100)}" y2="{y0}"/>',
                  f'<text class="tick" x="{_f(x0 + w * q / 100)}" y="{y0 + 18}" text-anchor="middle">{q} %</text>']
    for q in QUARTERS:
        parts += [f'<line class="grid" data-axis="y" data-value="{q}" x1="{x0}" y1="{_f(y0 - h * q / 100)}" '
                  f'x2="{x0 + w}" y2="{_f(y0 - h * q / 100)}"/>',
                  f'<text class="tick" x="{left - 8}" y="{_f(y0 - h * q / 100 + 4)}" text-anchor="end">{q} %</text>']
    parts.append(f'<line class="diagonal" data-diagonal="{_e(label)}" x1="{x0}" y1="{y0}" x2="{x0 + w}" y2="{y0 - h}"/>'
                 f'<text class="series-label random" x="{_f(px(n * 0.78) + 10)}" y="{_f(py(0.78) + 18)}">Al azar</text>')
    for e in evaluations:
        points = " ".join(f"{_f(px(p['k']))},{_f(py(p['capture']))}" for p in e["curve"])
        parts.append(f'<polyline class="series m-{_e(e["model_id"])}" data-capture="{_e(e["model_id"])}" points="{points}"/>')
    k = evaluations[0]["k_applied"]
    parts += [f'<line class="capacity" x1="{_f(px(k))}" y1="{top}" x2="{_f(px(k))}" y2="{y0}"/>',
              f'<text class="today" x="{_f(px(k) + 6)}" y="{top + 14}">Capacidad de hoy: {format_count(k)} clientes</text>']
    # series names next to where the lines cross «Hoy», pushed apart so they never overlap
    placed, min_gap = [], 21.0
    for e in sorted(evaluations, key=lambda e: -e["at_k"]["capture"]):
        y = py(e["at_k"]["capture"]) + 4
        if placed and y - placed[-1][1] < min_gap:
            y = placed[-1][1] + min_gap
        placed.append((e, y))
    for e, y in placed:
        parts.append(f'<circle class="at-k m-{_e(e["model_id"])}" cx="{_f(px(k))}" cy="{_f(py(e["at_k"]["capture"]))}" r="4"/>'
                     f'<text class="series-label m-{_e(e["model_id"])}" data-series-label="{_e(e["model_id"])}" '
                     f'x="{_f(px(k) + 12)}" y="{_f(y)}">{_plain(e["model_id"])}</text>')
    parts += [f'<text class="axis-title" x="{x0 + w / 2:.0f}" y="{height - 12}" text-anchor="middle">'
              'Clientes contactados, del más al menos riesgoso según cada modelo</text>',
              f'<text class="axis-title" x="14" y="{top + h / 2:.0f}" text-anchor="middle" '
              f'transform="rotate(-90 14 {top + h / 2:.0f})">Exposición en riesgo encontrada</text>']
    title = f"Exposición en riesgo encontrada según clientes contactados · {PLAIN_NAMES.get(label, label)}"
    return (f'<svg class="capture" data-capture-curve="{_e(label)}" data-x0="{x0}" data-y0="{y0}" '
            f'data-w="{w}" data-h="{h}" viewBox="0 0 {width} {height}" role="img" aria-label="{_e(title)}">'
            f'<title>{_e(title)}</title>{"".join(parts)}</svg>')


def _model_legend(evaluations: list, *extra: str) -> str:
    items = "".join(f'<li><span class="swatch m-{_e(e["model_id"])}"></span>{_plain(e["model_id"])}</li>'
                    for e in evaluations)
    return f'<ul class="legend">{items}{"".join(extra)}</ul>'


def _capture_card(data: dict) -> str:
    labels = _by_label(data)
    if not labels:
        return ""
    inputs, figures, rules = "", "", ""
    for n, (label, evaluations) in enumerate(labels.items()):
        checked = " checked" if n == 0 else ""
        inputs += (f'<input type="radio" name="capture-label" id="capture-{_e(label)}"{checked}>'
                   f'<label for="capture-{_e(label)}">{_plain(label)}</label>')
        figures += (f'<figure data-capture-for="{_e(label)}"><h4 data-capture-title="{_e(label)}">'
                    f'{_capture_title(label, evaluations)}</h4>{capture_svg(label, evaluations)}'
                    + _model_legend(evaluations, '<li><span class="swatch random"></span>Al azar</li>',
                                    '<li><span class="swatch capacity"></span>Capacidad de hoy</li>')
                    + '</figure>')
        rules += f'#capture-{label}:checked ~ figure[data-capture-for="{label}"] {{ display: block; }}'
    return (f'<div class="card" id="models-capture"><h3>¿Qué modelo encuentra más exposición en riesgo?</h3>'
            f'<style>.capture-switch figure {{ display: none; }} {rules}</style>'
            f'<div class="capture-switch">{inputs}{figures}</div>'
            + _how("Cada línea ordena a los clientes del más al menos riesgoso según el modelo y acumula la "
                   "exposición en riesgo que va encontrando.",
                   "Cuanto más arriba de la diagonal gris (azar), mejor ordena el modelo.",
                   "La línea punteada vertical es la capacidad de hoy: los clientes que el banco alcanza a llamar.")
            + '<p class="note">La curva de captura no depende de los supuestos de valor.</p></div>')


def _card_name(card: dict) -> str:
    return _plain(card["model_id"]) + (" (demostración)" if card["demo"] else "")


def _cards_table(cards: list) -> str:
    rows = ""
    for card in cards:
        text, cls = CARD_DECISIONS[card["decision"]]
        reasons = "; ".join(CARD_RULES.get(r["rule"], r["rule"]) for r in card["reasons"]) or DASH
        messages = "".join(f'<li><code>{_e(r["rule"])}</code> ({_e(r["severity"])}): {_e(r["message"])}</li>'
                           for r in card["reasons"])
        rows += (f'<tr data-card-row="{_e(card["file"])}"><td>{_e(_card_name(card))}</td>'
                 f'<td>{_plain(card["target"])}</td>'
                 f'<td><span class="status {cls}">{text}</span></td><td>{_e(reasons)}</td>'
                 f'<td><details><summary>Detalle</summary><code>{_e(card["file"])}</code> · estado '
                 f'{_e(card["status"])}<ul class="plain">{messages}</ul></details></td></tr>')
    return ('<div class="card" id="models-cards"><table class="data"><caption>Fichas de modelo</caption>'
            '<thead><tr><th>Modelo</th><th>Objetivo</th><th>Decisión</th><th>Motivo</th><th></th></tr></thead>'
            f'<tbody>{rows}</tbody></table><p class="note">El control de fichas revisa lo que declara cada ficha '
            '(fechas, huella del archivo, preprocesamiento); no puede probar por sí solo cómo se entrenó un modelo '
            'externo.</p></div>')


def _metrics_row(key: str, name: str, point: dict, metrics: dict | None, k_star: dict | None,
                 breakeven=None) -> str:
    m = metrics or {}
    cells = [format_pct(point["capture"]), format_cop_m(point["captured_cop_m"]), format_ratio(point["lift"]),
             format_pct(point["precision"]), format_pct(point["recall"]), format_ratio(m.get("pr_auc")),
             format_ratio(m.get("brier")),
             format_cop_m(point["net_value_cop_m"]), format_count(k_star["k"]) if k_star else DASH,
             format_cop_m(k_star["net_value_cop_m"]) if k_star else DASH, format_pct(breakeven)]
    return f'<tr data-metrics="{_e(key)}"><td>{name}</td>' + "".join(f'<td class="num">{c}</td>' for c in cells) + "</tr>"


def calibration_svg(key: str, model_id: str, calibration: list) -> str:
    """Mean score against the observed rate per decile: on the diagonal, the probabilities can be trusted."""
    size, pad = 220, 34
    inner = size - 2 * pad + 10
    x = lambda v: pad + inner * v
    y = lambda v: pad - 10 + inner * (1 - v)
    parts = [f'<rect class="frame" x="{pad}" y="{pad - 10}" width="{inner}" height="{inner}"/>',
             f'<line class="diagonal" x1="{_f(x(0))}" y1="{_f(y(0))}" x2="{_f(x(1))}" y2="{_f(y(1))}"/>']
    for b in calibration:
        parts.append(f'<circle class="calib-point m-{_e(model_id)}" cx="{_f(x(b["mean_score"]))}" '
                     f'cy="{_f(y(b["observed_rate"]))}" r="4"><title>Decil {_e(b["bin"])}: score medio '
                     f'{format_pct(b["mean_score"])}, tasa observada {format_pct(b["observed_rate"])}</title></circle>')
    parts += [f'<text class="tick" x="{pad}" y="{size - 6}">0 %</text>',
              f'<text class="tick" x="{_f(x(1))}" y="{size - 6}" text-anchor="end">100 %</text>',
              f'<text class="tick" x="{pad - 4}" y="{_f(y(1) + 4)}" text-anchor="end">100 %</text>']
    title = f"Calibración · {PLAIN_NAMES.get(model_id, model_id)}"
    return (f'<svg class="calib" data-calibration-chart="{_e(key)}" viewBox="0 0 {size} {size}" role="img" '
            f'aria-label="{_e(title)}"><title>{_e(title)}</title>{"".join(parts)}</svg>')


def _metrics_table(label: str, entries: list) -> str:
    groups = "".join(f'<th colspan="{len(cols)}" class="group">{q}</th>' for q, cols in METRIC_GROUPS)
    columns = "".join(f'<th class="num">{c}</th>' for _, cols in METRIC_GROUPS for c in cols)
    width = sum(len(cols) for _, cols in METRIC_GROUPS)
    rows, evaluated = "", None
    for e in entries:
        key = f'{label}.{e["model_id"]}'
        name = _named(_plain(e["model_id"]), e["model_id"])
        if e["status"] != "evaluated":
            missing = e.get("missing_score_rows")
            detail = f" ({format_count(missing)} filas sin score)" if missing else ""
            rows += (f'<tr data-metrics="{_e(key)}"><td>{name}</td><td colspan="{width}">No evaluado: '
                     f'{_e(NOT_EVALUATED.get(e["reason"], e["reason"]))}{detail}</td></tr>')
            continue
        evaluated = e
        rows += _metrics_row(key, name, e["at_k"], e["metrics"], e["k_star"], e["breakeven_effectiveness"])
    if evaluated:
        rows += _metrics_row(f"{label}.random", _plain("random"), evaluated["random_at_k"], None, None)
    k = f"llamando a {format_count(evaluated['k_applied'])} clientes (K, capacidad de hoy)" if evaluated else "con la capacidad de hoy"
    return (f'<table class="data metrics"><caption>Métricas {k} · {_plain(label)}</caption><thead>'
            f'<tr><th rowspan="2">Modelo</th>{groups}</tr><tr>{columns}</tr></thead><tbody>{rows}</tbody></table>')


def _calibration_block(label: str, entries: list) -> str:
    evaluated = [e for e in entries if e["status"] == "evaluated"]
    if not evaluated:
        return ""
    charts = "".join(f'<figure>{calibration_svg(f"{label}.{e["model_id"]}", e["model_id"], e["metrics"]["calibration"])}'
                     f'<figcaption>{_plain(e["model_id"])}</figcaption></figure>' for e in evaluated)
    rows = "".join(
        f'<tr data-calibration="{_e(label)}.{_e(e["model_id"])}"><td>{_plain(e["model_id"])}</td><td>{_e(b["bin"])}</td>'
        f'<td class="num">{format_count(b["n_clients"])}</td><td class="num">{format_pct(b["mean_score"])}</td>'
        f'<td class="num">{format_pct(b["observed_rate"])}</td></tr>' for e in evaluated for b in e["metrics"]["calibration"])
    return (f'<h4>¿Son confiables sus probabilidades? · {_plain(label)}</h4><div class="calib-grid">{charts}</div>'
            + _how("Cada punto es un decil de clientes: el score medio que dio el modelo contra la tasa que se observó.",
                   "Sobre la diagonal, las probabilidades se pueden leer como tales; por encima, el modelo se queda corto.")
            + f'<details class="deciles"><summary>Tabla por decil</summary><table class="data"><caption>Calibración por '
            f'decil · {_plain(label)}</caption><thead><tr><th>Modelo</th><th>Decil</th><th class="num">Clientes</th>'
            f'<th class="num">Score medio</th><th class="num">Tasa observada</th></tr></thead><tbody>{rows}</tbody>'
            '</table></details>')


def _technical_detail(data: dict) -> str:
    labels: dict = {}
    for e in data["models"]["evaluations"]:
        labels.setdefault(e["label"], []).append(e)
    inputs, panels, rules = "", "", ""
    for n, (label, entries) in enumerate(labels.items()):
        entries = sorted(entries, key=lambda e: e["model_id"])
        checked = " checked" if n == 0 else ""
        inputs += (f'<input type="radio" name="metrics-label" id="metrics-{_e(label)}"{checked}>'
                   f'<label for="metrics-{_e(label)}">{_plain(label)}</label>')
        panels += (f'<div class="metrics-panel" data-metrics-for="{_e(label)}">{_metrics_table(label, entries)}'
                   f'{_calibration_block(label, entries)}</div>')
        rules += f'#metrics-{label}:checked ~ .metrics-panel[data-metrics-for="{label}"] {{ display: block; }}'
    return (f'<details class="technical" id="models-technical"><summary>Detalle técnico</summary>'
            f'<style>.metrics-switch .metrics-panel {{ display: none; }} {rules}</style>'
            f'<div class="metrics-switch">{inputs}{panels}</div>'
            '<p class="note">K es la capacidad de hoy; K*, el mejor número de contactos: el que maximiza el valor neto. '
            'Efectividad mínima: la efectividad de la acción con la que las llamadas apenas se pagan.</p></details>')


def _models_view(data: dict) -> str:
    cards = "".join(_decision_card(d, data) for d in data["models"]["decisions"])
    return (f'<section class="view" id="modelos"><h2 class="view-title">{dict(TABS)["modelos"]}</h2>'
            f'<p class="q">{MODELS_QUESTION}</p><p class="answer" id="models-answer">{_models_answer(data)}</p>'
            f'{_verdict_cards(data)}<div class="stack" id="models-intervals">{cards}</div>'
            f'<div class="stack">{_capture_card(data)}{_cards_table(data["models"]["cards"])}</div>'
            f'{_technical_detail(data)}'
            f'<p class="pending" id="slices-pending">{SLICES_PENDING}</p>'
            f'<p class="note" id="models-simulated">{SIMULATED_NOTE}</p></section>')


# --- management view: answer, three questions, budget bar, charts, active risks ------------------

MANAGEMENT_QUESTION = "¿Vamos a tiempo y dentro del presupuesto?"
OPEN_SPRINT_NOTE = ("EV solo reconoce los SP cerrados con DoD («No attachment, no Done»): un sprint sin cerrar "
                    "baja el EV y arrastra SPI, CPI y EAC hasta su cierre.")
SP_TICK_STEPS = (1, 2, 5, 10, 20, 50)
COP_TICK_STEPS = (5, 10, 20, 25, 50, 100, 200)


def _hours(value) -> str:
    return f"{format_ratio(value)} h"


def _eac_line(cumulative: dict) -> str:
    over, gap = cumulative["eac_over_ceiling"], cumulative["eac_minus_ceiling_cop_m"]
    ceiling = format_cop_m(cumulative["ceiling_cop_m"])
    if over is None or gap is None:
        cls, text = "warn", "EAC: no se puede estimar todavía (sin valor ganado)."
    elif over:
        cls, text = "bad", f"El EAC supera el techo de {ceiling} por {format_cop_m(gap)}."
    else:
        cls, text = "ok", f"El EAC está dentro del techo de {ceiling}: margen de {format_cop_m(-gap)}."
    return f'<p id="eac-ceiling"><span class="status {cls}">EAC</span> {text}</p>'


def _yes_no(index) -> str:
    if index is None:
        return '<p class="mgmt-answer warn">Sin datos</p>'
    return '<p class="mgmt-answer yes">Sí</p>' if index >= 1 else '<p class="mgmt-answer no">No</p>'


def _traced_value(key: str, text: str, data: dict) -> tuple[str, str]:
    """(the value in its span, its trace): the trace goes after the sentence, never inside it."""
    attribute, trace = _traced(f"management.cumulative.{key}", data)
    return f'<span{attribute}>{text}</span>', trace


def _management_cards(management: dict, data: dict) -> str:
    c = management["cumulative"]
    spi, cpi = format_ratio(c["spi"]), format_ratio(c["cpi"])
    (spi_v, spi_t), (cpi_v, cpi_t) = _traced_value("spi", spi, data), _traced_value("cpi", cpi, data)
    eac_v, eac_t = _traced_value("eac_cop_m", format_cop_m(c["eac_cop_m"]), data)
    on_time = (f'<article class="mgmt-card" data-question="on-time"><h3>¿Vamos a tiempo?</h3>{_yes_no(c["spi"])}'
               f'<p>Por cada $1 de trabajo planeado se entregaron ${spi} (SPI {spi_v}).</p>{spi_t}</article>')
    on_budget = (f'<article class="mgmt-card" data-question="on-budget"><h3>¿Gastamos lo previsto?</h3>'
                 f'{_yes_no(c["cpi"])}<p>Por cada $1 gastado se generaron ${cpi} de valor (CPI {cpi_v}).</p>'
                 f'{cpi_t}</article>')
    final = (f'<article class="mgmt-card" data-question="final-cost"><h3>¿Cuánto costará al final?</h3>'
             f'<p class="mgmt-value">{eac_v}</p>'
             f'<p class="label-sm">EAC: proyección si se mantiene el ritmo de gasto</p>{_eac_line(c)}{eac_t}</article>')
    return f'<div class="mgmt-cards" id="management-cards">{on_time}{on_budget}{final}</div>'


def _budget_bar(management: dict) -> str:
    c = management["cumulative"]
    eac = c["eac_cop_m"]
    scale = max(v for v in (c["ceiling_cop_m"], c["bac_cop_m"], c["ac_cop_m"], eac or 0.0)) * 1.08
    pct = lambda v: f"{100 * v / scale:.2f}"
    marks = (f'<span class="mark" data-mark="bac" style="left:{pct(c["bac_cop_m"])}%"></span>'
             f'<span class="mark ceiling" data-mark="ceiling" style="left:{pct(c["ceiling_cop_m"])}%"></span>')
    eac_item = ""
    if eac is not None:
        over = c["eac_over_ceiling"]
        cls = "eac-dot over" if over else "eac-dot"
        marks += f'<span class="{cls}" data-mark="eac" style="left:{pct(eac)}%"></span>'
        eac_item = (f'<li><span class="swatch {"eac over" if over else "eac"}"></span>EAC, costo proyectado: '
                    f'<strong>{format_cop_m(eac)}</strong>{" (supera el techo)" if over else ""}</li>')
    return ('<div class="card" id="budget"><h3>Presupuesto</h3>'
            f'<p class="label-sm">Lo gastado hasta hoy (AC): <strong>{format_cop_m(c["ac_cop_m"])}</strong></p>'
            f'<div class="budget-track"><span class="budget-spent" data-mark="spent" style="width:{pct(c["ac_cop_m"])}%">'
            f'</span>{marks}</div>'
            '<ul class="legend budget-legend"><li><span class="swatch spent"></span>Gastado hasta hoy</li>'
            f'<li><span class="swatch bac"></span>BAC, presupuesto aprobado: <strong>{format_cop_m(c["bac_cop_m"])}'
            f'</strong></li><li><span class="swatch ceiling"></span>Techo del charter: '
            f'<strong>{format_cop_m(c["ceiling_cop_m"])}</strong></li>{eac_item}</ul></div><!-- /budget -->')


def _chart_frame(ticks: list[float], fmt, width: int, height: int, left: int, right: int, top: int, bottom: int):
    """Horizontal grid lines with their labels; returns (svg parts, y scale)."""
    low, high = ticks[0], ticks[-1]
    y = lambda v: top + (high - v) / ((high - low) or 1.0) * (height - top - bottom)
    parts = [f'<line class="grid" x1="{left}" y1="{y(t):.1f}" x2="{width - right}" y2="{y(t):.1f}"/>'
             f'<text class="tick" x="{left - 8}" y="{y(t) + 4:.1f}" text-anchor="end">{fmt(t)}</text>' for t in ticks]
    return parts, y


def _ticks(high: float, steps: tuple) -> list[float]:
    for step in steps:
        last = math.ceil(high / step) * step
        if last / step <= 5:
            break
    return [float(i * step) for i in range(int(round(last / step)) + 1)]


def _evm_chart(management: dict) -> str:
    sprints = management["sprints"]
    series = []
    for key, sid, name in (("ev_cop_m", "ev", "Valor ganado (EV)"), ("ac_cop_m", "ac", "Costo real (AC)"),
                           ("pv_cop_m", "pv", "Valor planeado (PV)")):   # PV last: dashed, over EV
        running, values = 0.0, []
        for s in sprints:
            running += s[key]
            values.append(running)
        series.append((sid, name, values))
    width, height, left, right, top, bottom = 960, 320, 100, 64, 16, 40
    ticks = _ticks(max(v for _, _, vs in series for v in vs), COP_TICK_STEPS)
    parts, y = _chart_frame(ticks, format_cop_m, width, height, left, right, top, bottom)
    n = len(sprints)
    x = lambda i: left + (width - left - right) * (i / (n - 1) if n > 1 else 0.5)
    for i, s in enumerate(sprints):
        parts.append(f'<text class="tick" x="{x(i):.1f}" y="{height - bottom + 20}" text-anchor="middle">'
                     f'Sprint {_e(s["sprint"])}</text>')
    for sid, name, values in series:
        points = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(values))
        parts.append(f'<polyline class="series evm-{sid}" data-series="{sid}" points="{points}"/>')
        for i, v in enumerate(values):
            parts.append(f'<circle class="dot evm-{sid}" cx="{x(i):.1f}" cy="{y(v):.1f}" r="5"><title>Sprint '
                         f'{_e(sprints[i]["sprint"])} · {sid.upper()} acumulado: {format_cop_m(v)}</title></circle>')
    # direct labels at the end, nudged apart when PV and EV coincide
    ends, used = sorted(((y(vs[-1]), sid) for sid, _, vs in series)), []
    for ly, sid in ends:
        while any(abs(ly - u) < 16 for u in used):
            ly += 16
        used.append(ly)
        parts.append(f'<text class="series-label" x="{x(n - 1) + 10:.1f}" y="{ly + 5:.1f}">{sid.upper()}</text>')
    legend = "".join(f'<li><span class="swatch evm-{sid}"></span>{name}</li>' for sid, name, _ in series)
    title = "PV, EV y AC acumulados por sprint, en COP"
    return (f'<div class="card" id="chart-evm"><h3>Valor planeado, ganado y costo real (acumulado)</h3>'
            f'<svg class="mgmt-chart" viewBox="0 0 {width} {height}" role="img" aria-label="{title}">'
            f'<title>{title}</title>{"".join(parts)}</svg><ul class="legend">{legend}</ul>'
            '<p class="note">PV va punteada encima de EV: si coinciden, se entregó lo planeado; si AC queda por encima de EV, '
            'cuesta más de lo que vale lo entregado.</p></div>')


def _velocity_chart(management: dict) -> str:
    velocity = management["velocity"]
    width, height, left, right, top, bottom = 640, 300, 56, 16, 16, 40
    ticks = _ticks(max([v["planned_sp"] for v in velocity] + [v["completed_sp"] for v in velocity]), SP_TICK_STEPS)
    parts, y = _chart_frame(ticks, format_count, width, height, left, right, top, bottom)
    slot = (width - left - right) / len(velocity)
    bar = min(48.0, slot / 3)
    for i, v in enumerate(velocity):
        center = left + slot * (i + 0.5)
        for offset, key, cls, word in ((-bar - 1, "planned_sp", "planned", "planeados"),
                                       (1, "completed_sp", "completed", "completados")):
            top_y = y(v[key])
            parts.append(f'<rect class="vbar {cls}" data-bar="{cls}-{_e(v["sprint"])}" x="{center + offset:.1f}" '
                         f'y="{top_y:.1f}" width="{bar:.1f}" height="{y(0) - top_y:.1f}" rx="3">'
                         f'<title>Sprint {_e(v["sprint"])}: {format_count(v[key])} SP {word}</title></rect>'
                         f'<text class="bar-label" x="{center + offset + bar / 2:.1f}" y="{top_y - 6:.1f}" '
                         f'text-anchor="middle">{format_count(v[key])}</text>')
        parts.append(f'<text class="tick" x="{center:.1f}" y="{height - bottom + 20}" text-anchor="middle">'
                     f'Sprint {_e(v["sprint"])}</text>')
    title = "SP planeados y completados por sprint"
    return (f'<div class="card" id="chart-velocity"><h3>Velocidad: SP planeados y completados</h3>'
            f'<svg class="mgmt-chart" viewBox="0 0 {width} {height}" role="img" aria-label="{title}">'
            f'<title>{title}</title>{"".join(parts)}</svg>'
            '<ul class="legend"><li><span class="swatch planned"></span>Planeados</li>'
            '<li><span class="swatch completed"></span>Completados</li></ul></div>')


def _burndown_chart(management: dict) -> str:
    if not management["burndown"]:
        return ""
    last = management["burndown"][-1]
    blocks = last["blocks"]
    width, height, left, right, top, bottom = 640, 300, 56, 40, 16, 40
    ticks = _ticks(max(max(b["ideal_remaining"], b["actual_remaining"]) for b in blocks), SP_TICK_STEPS)
    parts, y = _chart_frame(ticks, format_count, width, height, left, right, top, bottom)
    n = len(blocks)
    x = lambda i: left + (width - left - right) * (i / (n - 1) if n > 1 else 0.5)
    for i, b in enumerate(blocks):
        parts.append(f'<text class="tick" x="{x(i):.1f}" y="{height - bottom + 20}" text-anchor="middle">'
                     f'Bloque {_e(b["block"])}</text>')
    ideal = " ".join(f"{x(i):.1f},{y(b['ideal_remaining']):.1f}" for i, b in enumerate(blocks))
    actual = " ".join(f"{x(i):.1f},{y(b['actual_remaining']):.1f}" for i, b in enumerate(blocks))
    parts.append(f'<polyline class="series ideal" data-series="ideal" points="{ideal}"/>')
    parts.append(f'<polyline class="series actual" data-series="actual" points="{actual}"/>')
    for i, b in enumerate(blocks):
        parts.append(f'<circle class="dot actual" cx="{x(i):.1f}" cy="{y(b["actual_remaining"]):.1f}" r="5">'
                     f'<title>Bloque {_e(b["block"])}: quedan {format_decimal(b["actual_remaining"], 0)} SP</title>'
                     '</circle>')
    title = f"Burndown del Sprint {last['sprint']}: SP que quedan por bloque"
    return (f'<div class="card" id="chart-burndown"><h3>Burndown del Sprint {_e(last["sprint"])}</h3>'
            f'<svg class="mgmt-chart" viewBox="0 0 {width} {height}" role="img" aria-label="{_e(title)}">'
            f'<title>{_e(title)}</title>{"".join(parts)}</svg>'
            '<ul class="legend"><li><span class="swatch actual"></span>SP que quedan</li>'
            '<li><span class="swatch ideal"></span>Ritmo ideal</li></ul>'
            '<p class="note">Serie de sprint_metrics sobre docs/sprint_log.csv: cada historia baja en el bloque '
            'en que se cerró con DoD.</p></div>')


def _baseline_card(baseline: dict) -> str:
    crs = "".join(f'<dt data-change-request="{_e(cr["id"])}">{_e(cr["id"])} · sprint {_e(cr["sprint"])}</dt>'
                  f'<dd>{format_cop_m(cr["approved_cop_m"])} de la reserva al BAC</dd>'
                  for cr in baseline["change_requests"])
    return (
        '<div class="card" id="management-baseline"><h3>Línea base</h3><dl class="kv">'
        f'<dt>Techo del charter</dt><dd>{format_cop_m(baseline["ceiling_cop_m"])}</dd>'
        f'<dt>Contingencia</dt><dd>{format_cop_m(baseline["contingency_cop_m"])}</dd>{crs}'
        f'<dt>BAC</dt><dd>{format_cop_m(baseline["bac_cop_m"])}</dd>'
        f'<dt>Reserva restante</dt><dd>{format_cop_m(baseline["reserve_remaining_cop_m"])}</dd>'
        f'<dt>Tarifa</dt><dd>COP {format_count(baseline["rate_cop"])} por hora</dd>'
        f'<dt>Escala k</dt><dd>{format_ratio(baseline["k_scale"])}</dd>'
        f'<dt>Una hora registrada</dt><dd>{format_cop_m(baseline["logged_hour_cop_m"])}</dd>'
        '</dl></div>'
    )


def _cumulative_kv(management: dict) -> str:
    c = management["cumulative"]
    rows = ""
    for key, name, fmt in (("pv_cop_m", "PV (valor planeado)", format_cop_m), ("ev_cop_m", "EV (valor ganado)", format_cop_m),
                           ("ac_cop_m", "AC (costo real)", format_cop_m), ("spi", "SPI", format_ratio),
                           ("cpi", "CPI", format_ratio), ("eac_cop_m", "EAC (estimado al cierre)", format_cop_m),
                           ("bac_cop_m", "BAC", format_cop_m), ("ceiling_cop_m", "Techo del charter", format_cop_m)):
        rows += f'<dt>{name}</dt><dd>{fmt(c[key])}</dd>'
    sprints = ", ".join(str(s) for s in c["sprints"])
    return f'<div class="card"><h3>Acumulado · sprints {_e(sprints)}</h3><dl class="kv">{rows}</dl></div>'


def _sprints_table(management: dict) -> str:
    rows = ""
    for s in management["sprints"]:
        marker = ' <span class="status warn">reconstruidas</span>' if s["hours_estimated"] else ""
        rows += (f'<tr data-sprint="{_e(s["sprint"])}"><td>{_e(s["sprint"])}</td>'
                 f'<td>{format_count(s["done_sp"])} de {format_count(s["committed_sp"])}</td>'
                 f'<td>{format_cop_m(s["pv_cop_m"])}</td><td>{format_cop_m(s["ev_cop_m"])}</td>'
                 f'<td>{format_cop_m(s["ac_cop_m"])}</td><td>{format_ratio(s["spi"])}</td><td>{format_ratio(s["cpi"])}</td>'
                 f'<td>{_hours(s["logged_hours"])}{marker}</td><td>{_hours(s["mgmt_hours"])}</td></tr>')
    note = (f'<p class="note" id="open-sprint">{OPEN_SPRINT_NOTE}</p>'
            if any(s["done_sp"] < s["committed_sp"] for s in management["sprints"]) else "")
    return ('<div class="card"><table class="data"><caption>Valor ganado por sprint</caption><thead><tr>'
            '<th>Sprint</th><th>SP cerrados</th><th>PV</th><th>EV</th><th>AC</th><th>SPI</th><th>CPI</th>'
            '<th>Horas registradas</th><th>Horas de gestión</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>{note}'
            '<p class="note">Las horas de gestión (MGMT) cuentan en el AC, no en el EV. SP cerrados y velocidad '
            'salen del mismo docs/sprint_log.csv.</p></div>')


def _velocity_table(management: dict) -> str:
    rows = "".join(f'<tr data-velocity="{_e(v["sprint"])}"><td>{_e(v["sprint"])}</td>'
                   f'<td>{format_count(v["planned_sp"])}</td><td>{format_count(v["completed_sp"])}</td>'
                   f'<td>{format_pct(v["completion_rate_pct"] / 100)}</td></tr>' for v in management["velocity"])
    return ('<div class="card"><table class="data"><caption>Velocidad</caption><thead><tr><th>Sprint</th>'
            '<th>SP planeados</th><th>SP completados</th><th>Cumplimiento</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')


RISK_CATEGORIES = {"Data quality": "Calidad de datos", "Schedule": "Cronograma", "Scope": "Alcance",
                   "Compliance": "Cumplimiento normativo", "Business adoption": "Adopción del negocio",
                   "Budget": "Presupuesto", "Technology": "Tecnología"}
RISK_TYPES = {"Risk": "Riesgo", "Impediment": "Impedimento"}
RISK_PROBABILITY = {"High": "Alta", "Medium": "Media", "Low": "Baja"}
RISK_IMPACT = {"High": "Alto", "Medium": "Medio", "Low": "Bajo"}
RISK_STATUS = {"Open": "Abierto", "Mitigating": "En mitigación", "Closed": "Cerrado", "Monitoring": "En seguimiento",
               "Occurred": "Materializado"}
CLOSED_STATUS = "Closed"
# Translation of the register's text, by risk id: (the English text it translates, the Spanish text).
# Numbers are taken from the original; if the original changes, the original is shown, never a stale translation.
RISK_TEXT_ES = {
    "R-01": (r"Records may be incomplete or fragmented for forecasting use",
             "Los registros pueden estar incompletos o fragmentados para usarlos en pronósticos"),
    "R-02": (r"Analytical and validation work may extend beyond planned effort",
             "El trabajo de análisis y validación puede superar el esfuerzo planeado"),
    "R-03": (r"Requests for model development or system integration",
             "Solicitudes de desarrollo de modelos o de integración de sistemas (fuera del alcance)"),
    "R-04": (r"Data of (\d+) clients falls under Ley 1581 de 2012 \(Habeas Data\)",
             "Los datos de {0} clientes están sujetos a la Ley 1581 de 2012 (habeas data)"),
    "R-05": (r"Low uptake by the Risk and Analytics function",
             "Baja adopción por parte del área de Riesgo y Analítica"),
    "I-01": (r"Sponsor sign-off delayed stories at closure in the Cut 1 simulation",
             "La aprobación del patrocinador retrasó el cierre de historias en la simulación del Corte 1"),
}


def _risk_text(risk: dict) -> str:
    """Spanish description of a risk, escaped; the original when there is no matching translation."""
    pattern, spanish = RISK_TEXT_ES.get(risk["risk_id"], (None, None))
    match = re.fullmatch(pattern, risk["description"]) if pattern else None
    if match is None:
        return _e(risk["description"])
    return _e(spanish.format(*(format_count(int(g)) for g in match.groups())))


def _risk_status(risk: dict) -> str:
    """A closed impediment was resolved; a closed risk, closed."""
    if risk["status"] == CLOSED_STATUS and risk["type"] == "Impediment":
        return "Resuelto"
    return RISK_STATUS.get(risk["status"], risk["status"])


def _risk_rows(risks: list) -> str:
    return "".join(
        f'<tr data-risk="{_e(r["risk_id"])}"><td>{_e(r["risk_id"])}</td>'
        f'<td>{_e(RISK_TYPES.get(r["type"], r["type"]))}</td>'
        f'<td>{_e(RISK_CATEGORIES.get(r["category"], r["category"]))}</td><td>{_risk_text(r)}'
        f'<details class="original"><summary>Original</summary>{_e(r["description"])}</details></td>'
        f'<td>{_e(RISK_PROBABILITY.get(r["probability"], r["probability"]))}</td>'
        f'<td>{_e(RISK_IMPACT.get(r["impact"], r["impact"]))}</td><td>{_e(r["owner"])}</td>'
        f'<td>{_e(_risk_status(r))}</td></tr>' for r in risks)


RISK_HEAD = ('<thead><tr><th>Id</th><th>Tipo</th><th>Categoría</th><th>Descripción</th><th>Probabilidad</th>'
             '<th>Impacto</th><th>Responsable</th><th>Estado</th></tr></thead>')


def _risks_card(management: dict) -> str:
    active = [r for r in management["risks"] if r["status"] != CLOSED_STATUS]
    count = management["risk_reviews_count"]
    reviews = ("Sin revisiones registradas." if count == 0
               else f'{format_count(count)} revisiones registradas.')
    return ('<div class="card"><table class="data"><caption>Riesgos e impedimentos activos</caption>'
            f'{RISK_HEAD}<tbody>{_risk_rows(active)}</tbody></table>'
            f'<p class="note" id="risk-reviews">{reviews}</p></div>')


def _risks_detail(management: dict) -> str:
    closed = [r for r in management["risks"] if r["status"] == CLOSED_STATUS]
    closed_table = (f'<table class="data"><caption>Cerrados y resueltos (no se borran del registro)</caption>'
                    f'{RISK_HEAD}<tbody>{_risk_rows(closed)}</tbody></table>' if closed
                    else '<p class="note">Ningún riesgo ni impedimento cerrado.</p>')
    originals = "".join(
        f'<tr><td>{_e(r["risk_id"])}</td><td>{_e(r["type"])}</td><td>{_e(r["category"])}</td>'
        f'<td>{_e(r["description"])}</td><td>{_e(r["probability"])}</td><td>{_e(r["impact"])}</td>'
        f'<td>{_e(r["status"])}</td></tr>' for r in management["risks"])
    return (f'<div id="risks-closed">{closed_table}</div>'
            '<div id="risks-technical"><table class="data"><caption>data/risk_register.csv, tal como está</caption>'
            '<thead><tr><th>Id</th><th>Type</th><th>Category</th><th>Description</th><th>Probability</th>'
            f'<th>Impact</th><th>Status</th></tr></thead><tbody>{originals}</tbody></table></div>')


def _management_view(data: dict) -> str:
    management = data["management"]
    head = (f'<section class="view" id="gestion"><h2 class="view-title">{dict(TABS)["gestion"]}</h2>'
            f'<p class="q">{MANAGEMENT_QUESTION}</p>')
    hours_gate = ('<div class="card" id="management-hours-gate">'
                  + _gate1_table(data["gates"]["gate1"], ("hours_log",),
                                 "Gate 1 · registro de horas (control de proyecto de PCM, no es dato de FinBank)")
                  + '</div>')
    if management["status"] != "RUN":
        return (head + f'<div class="banner warn" id="management-not-run" role="status">La gestión no se calculó '
                f'en esta corrida: {_e(management["reason"])}.</div>{hours_gate}</section>')
    outside = management["hours_outside_reported_sprints"]
    hours_note = ""
    if outside:
        listed = ", ".join(f"sprint {_e(s)}: {_hours(h)}" for s, h in sorted(outside.items()))
        hours_note = (f'<p class="note" id="hours-outside">Horas registradas en sprints que aún no están en el '
                      f'sprint_log ({listed}): no entran en el valor ganado.</p>')
    technical = ('<details class="technical" id="management-technical"><summary>Detalle técnico: tablas por sprint, '
                 'línea base, registro de riesgos y Gate 1 de horas</summary>'
                 f'{_sprints_table(management)}{hours_note}<div class="grid two">{_velocity_table(management)}'
                 f'{_cumulative_kv(management)}</div>{_baseline_card(management["baseline"])}'
                 f'{_risks_detail(management)}{hours_gate}</details>')
    return (head + f'{_management_cards(management, data)}{_budget_bar(management)}'
            f'<div class="stack">{_evm_chart(management)}<div class="grid two">{_velocity_chart(management)}'
            f'{_burndown_chart(management)}</div></div>'
            f'{_risks_card(management)}{technical}</section>')


def render(data: dict) -> str:
    """The complete page. Raises ValueError if the data does not meet dashboard_data_v1."""
    errors = validate_dashboard_data(data)
    if errors:
        raise ValueError("dashboard_data_v1: " + "; ".join(errors[:5]))
    css = (ASSETS_DIR / "styles.css").read_text(encoding="utf-8")
    views = (_summary(data) + _data_view(data) + _trace_view(data) + _models_view(data) + _stress_view(data)
             + _management_view(data))
    return (
        '<!doctype html>\n<html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Predict360 · Tablero del comité</title>'
        f'<style>{css}</style>{_active_nav_style()}</head><body><div class="app">{_sidebar()}'
        f'<div class="main"><div class="banners">{_banners(data["meta"])}</div>{_header(data["meta"])}'
        f'<main>{views}</main>'
        '<footer>Generado por dashboard_render.py desde dashboard_data.json; ninguna cifra se escribe a mano.</footer>'
        '</div></div></body></html>\n'
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
