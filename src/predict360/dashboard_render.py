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
from datetime import date
from html import escape
from pathlib import Path

from src.predict360.dashboard_contract import validate_dashboard_data
from src.predict360.formatting import DASH, format_cop_m, format_count, format_figure, format_pct, format_ratio

ASSETS_DIR = Path(__file__).resolve().parent / "dashboard_assets"

TABS = [
    ("resumen", "Resumen"),
    ("datos", "Datos"),
    ("trazabilidad", "Trazabilidad"),
    ("modelos", "Modelos"),
    ("estres", "Decisión en COP"),
    ("gestion", "Gestión"),
    ("entrega", "Entrega"),
]
TAB_ICONS = {"resumen": "home", "datos": "db", "trazabilidad": "route", "modelos": "model", "estres": "coin", "gestion": "calendar",
             "entrega": "box"}
# The ONE place where technical ids get their name for a reader; ids stay in «Detalle técnico» only
PLAIN_NAMES = {
    "delinquency": "Mora temprana", "churn": "Fuga de clientes preferenciales",
    "delinquency_30": "Mora a 30 días", "delinquency_60": "Mora a 60 días", "churn_3m": "Fuga a 3 meses",
    "baseline_rule": "Regla actual", "model_a": "Modelo A", "model_b": "Modelo B", "model_c": "Modelo C",
    "random": "Azar", "tenure_months": "antigüedad",
}
GUIDED_STEPS = [
    {"tab": "resumen", "title": "Correr el pipeline y refrescar el tablero",
     "text": "Un solo comando (run_pipeline.py --config config/synthetic.yaml) corre las doce "
             "estaciones y escribe este tablero. Revise la exposición, la conciliación y los tres gates."},
    {"tab": "datos", "title": "Romper los datos",
     "text": "Con un archivo defectuoso, el Gate 1 se pone en rojo y dice qué regla falló."},
    {"tab": "trazabilidad", "title": "Rastrear una cifra hasta su origen",
     "text": "Abra el rastreo de la exposición de mora: archivo de origen, script, commit y hash."},
    {"tab": "modelos", "title": "Comparar modelos",
     "text": "Compare los modelos contra la regla base y el azar, revise las rebanadas y vea una "
             "ficha rechazada con su motivo."},
    {"tab": "estres", "title": "Mover el simulador",
     "text": "Cambie capacidad, efectividad y costo por contacto; observe el valor neto en COP y K*."},
    {"tab": "gestion", "title": "Gestión, evidencia y consistencia",
     "text": "Valor ganado, SPI, CPI y EAC contra el techo del presupuesto; registro de evidencia y Gate 3."},
]
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
    "box": '<path d="M3 7l9-4 9 4-9 4-9-4z"/><path d="M3 7v10l9 4 9-4V7"/><path d="M12 11v10"/>',
    "play": '<circle cx="12" cy="12" r="9"/><path d="M10 8.5v7l6-3.5z"/>',
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
__all__ =["GUIDED_STEPS", "TABS", "format_cop_m", "format_pct", "render", "write"]   # formatters re-exported


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


def _pill(cls: str, text: str, pill_id: str = "") -> str:
    """Soft status pill: colour, icon AND words, never colour alone. ``text`` is already HTML."""
    attribute = f' id="{pill_id}" role="status"' if pill_id else ""
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
            f'<nav aria-label="Vistas">{links}</nav>'
            f'<a class="present" href="#guia-1">{_icon("play")}<span>Presentar</span></a></aside>')


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
                 f'<td>{_e(e["model_id"])}</td><td>{_e(e["label"])}</td>'
                 f'<td{attribute}>{format_cop_m(vs["difference_cop_m"])}{trace}</td>'
                 f'<td>{format_cop_m(vs["ci_low_cop_m"])} a {format_cop_m(vs["ci_high_cop_m"])}</td>'
                 f'<td><span class="status {cls}">{text}</span></td></tr>')
    if not rows:
        return ""
    return ('<table class="compare"><thead><tr><th>Modelo</th><th>Etiqueta</th>'
            '<th>Diferencia en K</th><th>IC pareado</th><th>Resultado</th></tr></thead>'
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
    title = f"Valor neto en COP según K · {PLAIN_NAMES.get(label, label)}"
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
        cards += (f'<div class="card" data-sim-label="{_e(label)}"><h3>{_plain(label)}</h3>'
                  f'{curve_svg(label, evaluations, evaluations[0]["k_applied"])}{_legend(evaluations)}'
                  f'{_stress_table(label, evaluations, sim["rule"])}</div>')
    if not cards:
        cards = '<div class="pending">Sin modelos evaluados: no hay curvas que simular.</div>'
    return (
        f'<section class="view" id="estres"><h2>{dict(TABS)["estres"]}</h2>'
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


# --- models view: which model ranks best, and is the evidence enough? ---------------------------

DECISION_TAGS = {"authorized": ("Supera la regla", "ok"), "insufficient_evidence": ("Evidencia insuficiente", "warn"),
                 "does_not_beat_baseline": ("No supera la regla", "bad"),
                 "no_baseline": ("Sin regla base comparable", "warn"), "no_candidate": ("Sin modelo candidato", "warn")}
CARD_DECISIONS = {"ADMITTED": ("Admitida", "ok"), "REJECTED": ("Rechazada", "bad"), "SKIPPED": ("Omitida", "warn")}
NOT_EVALUATED = {"incomplete_scores": "scores incompletos"}
DELINQUENCY_RULE = ("Mora exige ganar a 30 y a 60 días: se autoriza solo si todo el intervalo supera el margen "
                    "en ambos horizontes.")
SLICES_PENDING = ("Rebanadas: pendiente (B8c). La primera será la de clientes con tenure_months faltante "
                  "(riesgo R-01, waiver W-01), evaluada aparte y sin imputar.")
SIMULATED_NOTE = ("Scores simulados: no son modelos entrenados. El sistema evalúa en COP cualquier modelo que "
                  "FinBank entrene; estos sirven para mostrar cómo.")


def _f(value: float) -> str:
    return f"{value:.3f}"


def _verdict_card(data: dict) -> str:
    items = ""
    for d in data["models"]["decisions"]:
        text, cls = VERDICTS[d["verdict"]]
        model = f' · {_e(d["model_id"])}' if d["model_id"] else ""
        items += f'<li>{_plain(d["target"])}: <span class="status {cls}">{text}</span>{model}</li>'
    authorized = [d for d in data["models"]["decisions"] if d["verdict"] == "authorized_for_shadow_deployment"]
    lead = ("Hay modelos autorizados a despliegue en sombra." if authorized
            else "Ningún objetivo tiene un modelo autorizado: la evidencia no alcanza para reemplazar la regla.")
    return (f'<div class="card" id="models-verdict"><h3>Dictamen</h3><p>{lead}</p><ul class="plain">{items}</ul>'
            '<p class="note">El dictamen más alto posible es «autorizado a despliegue en sombra».</p></div>')


def ci_svg(target: str, rows: list) -> str:
    """Point advantage over the rule and its paired interval, against zero (and the margin)."""
    width, left, right, top, row_h, bottom = 640, 150, 16, 26, 28, 26
    height = top + row_h * len(rows) + bottom
    margin = rows[0]["vs_baseline"]["margin_cop_m"]
    values = [0.0, margin] + [v for e in rows for v in (e["vs_baseline"]["ci_low_cop_m"], e["vs_baseline"]["ci_high_cop_m"])]
    low, high = min(values), max(values)
    pad = (high - low) * 0.05 or 1.0
    vmin, vmax = low - pad, high + pad
    scale = (width - left - right) / (vmax - vmin)
    x = lambda v: left + (v - vmin) * scale
    bottom_y = height - bottom
    parts = [f'<rect class="rule-better" x="{left}" y="{top}" width="{_f(x(0.0) - left)}" height="{bottom_y - top}"/>',
             f'<text class="tick" x="{left + 4}" y="{top - 8}">la regla es mejor</text>',
             f'<line class="zero" x1="{_f(x(0.0))}" y1="{top}" x2="{_f(x(0.0))}" y2="{bottom_y}"/>']
    if margin:
        parts.append(f'<line class="margin" x1="{_f(x(margin))}" y1="{top}" x2="{_f(x(margin))}" y2="{bottom_y}"/>')
    for i, e in enumerate(rows):
        vs = e["vs_baseline"]
        cy = top + row_h * i + row_h / 2
        _, cls = OUTCOMES[vs["outcome"]]
        parts.append(
            f'<g data-ci="{_e(e["label"])}.{_e(e["model_id"])}" class="{cls}">'
            f'<text class="tick" x="{left - 8}" y="{cy + 4:.1f}" text-anchor="end">{_e(e["model_id"])} · '
            f'{_plain(e["label"])}</text>'
            f'<line class="ci-range" x1="{_f(x(vs["ci_low_cop_m"]))}" y1="{cy:.1f}" x2="{_f(x(vs["ci_high_cop_m"]))}" '
            f'y2="{cy:.1f}"/><circle class="ci-point" cx="{_f(x(vs["difference_cop_m"]))}" cy="{cy:.1f}" r="4">'
            f'<title>{format_cop_m(vs["difference_cop_m"])} · IC {format_cop_m(vs["ci_low_cop_m"])} a '
            f'{format_cop_m(vs["ci_high_cop_m"])}</title></circle></g>')
    for v, anchor in ((vmin, "start"), (0.0, "middle"), (vmax, "end")):
        if v != 0.0 and abs(x(v) - x(0.0)) < 80:          # keep the zero label readable
            continue
        parts.append(f'<text class="tick" x="{_f(x(v))}" y="{height - 8}" text-anchor="{anchor}">{format_cop_m(v)}</text>')
    title = f"Ventaja sobre la regla con su intervalo pareado · {PLAIN_NAMES.get(target, target)}"
    return (f'<svg class="ci" data-ci-target="{_e(target)}" data-vmin="{vmin!r}" data-x0="{left}" '
            f'data-xscale="{scale!r}" viewBox="0 0 {width} {height}" role="img" aria-label="{_e(title)}">'
            f'<title>{_e(title)}</title>{"".join(parts)}</svg>')


def _decision_card(decision: dict, data: dict) -> str:
    target = decision["target"]
    tag, cls = DECISION_TAGS[decision["reason_code"]]
    rule = f" {DELINQUENCY_RULE}" if target == "delinquency" else ""
    rows = sorted((e for e in data["models"]["evaluations"] if e["target"] == target and e["status"] == "evaluated"
                   and e["vs_baseline"]), key=lambda e: (e["model_id"], e["label"]))
    body = (ci_svg(target, rows) + _comparisons(target, data) if rows
            else f'<p class="label-sm" id="ci-none-{_e(target)}">Sin comparación contra la regla: {_e(decision["reason"])}</p>')
    return (f'<div class="card" data-decision-card="{_e(target)}"><h3>{_plain(target)}</h3>'
            f'<p><span class="status {cls}" data-decision-tag="{_e(target)}">{tag}</span>{rule}</p>{body}</div>')


def capture_svg(label: str, evaluations: list) -> str:
    """Share of the at-risk exposure found against the share of clients contacted; needs no assumption."""
    width, height, left, right, top, bottom = 640, 300, 56, 16, 16, 40
    w, h = width - left - right, height - top - bottom
    x0, y0 = left, top + h
    n = evaluations[0]["n_clients"]
    px = lambda k: x0 + w * k / n
    py = lambda capture: y0 - h * capture
    parts = [f'<line class="diagonal" data-diagonal="{_e(label)}" x1="{x0}" y1="{y0}" x2="{x0 + w}" y2="{y0 - h}"/>']
    for i, e in enumerate(evaluations):
        points = " ".join(f"{_f(px(p['k']))},{_f(py(p['capture']))}" for p in e["curve"])
        parts.append(f'<polyline class="series s{i}" data-capture="{_e(e["model_id"])}" points="{points}"/>')
    k = evaluations[0]["k_applied"]
    parts += [f'<line class="capacity" x1="{_f(px(k))}" y1="{top}" x2="{_f(px(k))}" y2="{y0}"/>',
              f'<text class="tick" x="{left - 6}" y="{y0 - h + 4}" text-anchor="end">100 %</text>',
              f'<text class="tick" x="{left - 6}" y="{y0 + 4}" text-anchor="end">0 %</text>',
              f'<text class="tick" x="{x0 + w}" y="{y0 + 16}" text-anchor="end">100 %</text>',
              f'<text class="tick" x="{(left + width - right) / 2:.0f}" y="{height - 6}" text-anchor="middle">'
              '% de clientes contactados</text>']
    title = f"Exposición en riesgo encontrada según clientes contactados · {PLAIN_NAMES.get(label, label)}"
    return (f'<svg class="capture" data-capture-curve="{_e(label)}" data-x0="{x0}" data-y0="{y0}" '
            f'data-w="{w}" data-h="{h}" viewBox="0 0 {width} {height}" role="img" aria-label="{_e(title)}">'
            f'<title>{_e(title)}</title>{"".join(parts)}</svg>')


def _capture_card(data: dict) -> str:
    labels = _by_label(data)
    if not labels:
        return ""
    inputs, figures, rules = "", "", ""
    for n, (label, evaluations) in enumerate(labels.items()):
        name = _plain(label)
        checked = " checked" if n == 0 else ""
        inputs += (f'<input type="radio" name="capture-label" id="capture-{_e(label)}"{checked}>'
                   f'<label for="capture-{_e(label)}">{name}</label>')
        items = "".join(f'<li><span class="swatch s{i}"></span>{_e(e["model_id"])}</li>' for i, e in enumerate(evaluations))
        figures += (f'<figure data-capture-for="{_e(label)}">{capture_svg(label, evaluations)}<ul class="legend">{items}'
                    '<li><span class="swatch random"></span>azar (diagonal)</li>'
                    '<li><span class="swatch capacity"></span>capacidad actual</li></ul></figure>')
        rules += f'#capture-{label}:checked ~ figure[data-capture-for="{label}"] {{ display: block; }}'
    return (f'<div class="card" id="models-capture"><h3>¿Qué modelo encuentra más exposición en riesgo?</h3>'
            f'<style>.capture-switch figure {{ display: none; }} {rules}</style>'
            f'<div class="capture-switch">{inputs}{figures}</div>'
            '<p class="note">Curva de captura: no depende de supuestos de valor. Cuanto más arriba de la diagonal, '
            'mejor ordena el modelo.</p></div>')


def _cards_table(cards: list) -> str:
    rows = ""
    for card in cards:
        text, cls = CARD_DECISIONS[card["decision"]]
        reasons = "; ".join(CARD_RULES.get(r["rule"], r["rule"]) for r in card["reasons"]) or DASH
        demo = ' <span class="status warn">Ficha de demostración</span>' if card["demo"] else ""
        messages = "".join(f'<li><code>{_e(r["rule"])}</code> ({_e(r["severity"])}): {_e(r["message"])}</li>'
                           for r in card["reasons"])
        rows += (f'<tr data-card-row="{_e(card["file"])}"><td>{_e(card["model_id"])}{demo}</td>'
                 f'<td>{_plain(card["target"])}</td>'
                 f'<td><span class="status {cls}">{text}</span></td><td>{_e(reasons)}</td>'
                 f'<td><details><summary>Detalle</summary><code>{_e(card["file"])}</code> · estado '
                 f'{_e(card["status"])}<ul class="plain">{messages}</ul></details></td></tr>')
    return ('<div class="card" id="models-cards"><table class="data"><caption>Fichas de modelo (Gate 2)</caption>'
            '<thead><tr><th>Modelo</th><th>Objetivo</th><th>Decisión</th><th>Motivo</th><th></th></tr></thead>'
            f'<tbody>{rows}</tbody></table><p class="note">Gate 2 revisa lo que declara la ficha (fechas, hash, '
            'preprocesamiento); no puede probar por sí solo cómo se entrenó un modelo externo.</p></div>')


def _metrics_row(key: str, name: str, point: dict, metrics: dict | None, k_star: dict | None) -> str:
    m = metrics or {}
    cells = [format_pct(point["capture"]), format_cop_m(point["captured_cop_m"]), format_cop_m(point["net_value_cop_m"]),
             format_pct(point["precision"]), format_pct(point["recall"]), format_ratio(point["lift"]),
             format_ratio(m.get("pr_auc")), format_ratio(m.get("brier")),
             format_count(k_star["k"]) if k_star else DASH, format_cop_m(k_star["net_value_cop_m"]) if k_star else DASH]
    return f'<tr data-metrics="{_e(key)}"><td>{_e(name)}</td>' + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def _technical_detail(data: dict) -> str:
    labels: dict = {}
    for e in data["models"]["evaluations"]:
        labels.setdefault(e["label"], []).append(e)
    tables = ""
    for label, entries in labels.items():
        rows, calibration, evaluated = "", "", None
        for e in sorted(entries, key=lambda e: e["model_id"]):
            key = f'{label}.{e["model_id"]}'
            if e["status"] != "evaluated":
                reason = NOT_EVALUATED.get(e["reason"], e["reason"])
                missing = e.get("missing_score_rows")
                detail = f" ({format_count(missing)} filas sin score)" if missing else ""
                rows += (f'<tr data-metrics="{_e(key)}"><td>{_e(e["model_id"])}</td>'
                         f'<td colspan="10">No evaluado: {_e(reason)}{detail}</td></tr>')
                continue
            evaluated = e
            rows += _metrics_row(key, e["model_id"], e["at_k"], e["metrics"], e["k_star"])
            calibration += "".join(
                f'<tr data-calibration="{_e(key)}"><td>{_e(e["model_id"])}</td><td>{_e(b["bin"])}</td>'
                f'<td>{format_count(b["n_clients"])}</td><td>{format_pct(b["mean_score"])}</td>'
                f'<td>{format_pct(b["observed_rate"])}</td></tr>' for b in e["metrics"]["calibration"])
        if evaluated:
            rows += _metrics_row(f"{label}.random", "azar", evaluated["random_at_k"], None, None)
        name = _plain(label)
        tables += ('<table class="data"><caption>Métricas en la K aplicada · ' + name + '</caption><thead><tr>'
                   '<th>Modelo</th><th>Captura</th><th>Capturado</th><th>Valor neto</th><th>Precisión</th>'
                   '<th>Recall</th><th>Lift</th><th>PR-AUC</th><th>Brier</th><th>K*</th><th>Valor neto en K*</th>'
                   f'</tr></thead><tbody>{rows}</tbody></table>')
        if calibration:
            tables += ('<table class="data"><caption>Calibración por decil · ' + name + '</caption><thead><tr>'
                       '<th>Modelo</th><th>Decil</th><th>Clientes</th><th>Score medio</th><th>Tasa observada</th>'
                       f'</tr></thead><tbody>{calibration}</tbody></table>')
    return (f'<details class="technical" id="models-technical"><summary>Detalle técnico</summary>{tables}</details>')


def _models_view(data: dict) -> str:
    cards = "".join(_decision_card(d, data) for d in data["models"]["decisions"])
    return (f'<section class="view" id="modelos"><h2>{dict(TABS)["modelos"]}</h2>'
            f'{_verdict_card(data)}<div class="stack">{cards}</div>{_capture_card(data)}'
            f'{_cards_table(data["models"]["cards"])}<div class="card">{_technical_detail(data)}</div>'
            f'<p class="pending" id="slices-pending">{SLICES_PENDING}</p>'
            f'<p class="note" id="models-simulated">{SIMULATED_NOTE}</p></section>')


# --- management view: EVM, velocity and risks ------------------------------------------------

OPEN_SPRINT_NOTE = ("EV solo reconoce los SP cerrados con DoD («No attachment, no Done»): un sprint sin cerrar "
                    "baja el EV y arrastra SPI, CPI y EAC hasta su cierre.")


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


def _cumulative_card(management: dict, data: dict) -> str:
    c = management["cumulative"]
    rows = ""
    for key, name, fmt in (("pv_cop_m", "PV (valor planeado)", format_cop_m), ("ev_cop_m", "EV (valor ganado)", format_cop_m),
                           ("ac_cop_m", "AC (costo real)", format_cop_m), ("spi", "SPI", format_ratio),
                           ("cpi", "CPI", format_ratio), ("eac_cop_m", "EAC (estimado al cierre)", format_cop_m),
                           ("bac_cop_m", "BAC", format_cop_m), ("ceiling_cop_m", "Techo del charter", format_cop_m)):
        attribute, trace = _traced(f"management.cumulative.{key}", data)
        rows += f'<dt>{name}</dt><dd><span{attribute}>{fmt(c[key])}</span>{trace}</dd>'
    sprints = ", ".join(str(s) for s in c["sprints"])
    return (f'<div class="card" id="management-cumulative"><h3>Acumulado · sprints {_e(sprints)}</h3>'
            f'<dl class="kv">{rows}</dl>{_eac_line(c)}</div>')


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
            '<p class="note">Las horas de gestión (MGMT) cuentan en el AC, no en el EV.</p></div>')


def _velocity_table(management: dict) -> str:
    rows = "".join(f'<tr data-velocity="{_e(v["sprint"])}"><td>{_e(v["sprint"])}</td>'
                   f'<td>{format_count(v["planned_sp"])}</td><td>{format_count(v["completed_sp"])}</td>'
                   f'<td>{format_pct(v["completion_rate_pct"] / 100)}</td></tr>' for v in management["velocity"])
    return ('<div class="card"><table class="data"><caption>Velocidad</caption><thead><tr><th>Sprint</th>'
            '<th>SP planeados</th><th>SP completados</th><th>Cumplimiento</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')


def _risks_table(management: dict) -> str:
    rows = "".join(f'<tr data-risk="{_e(r["risk_id"])}"><td>{_e(r["risk_id"])}</td><td>{_e(r["category"])}</td>'
                   f'<td>{_e(r["description"])}</td><td>{_e(r["probability"])}</td><td>{_e(r["impact"])}</td>'
                   f'<td>{_e(r["owner"])}</td><td>{_e(r["status"])}</td></tr>' for r in management["risks"])
    count = management["risk_reviews_count"]
    reviews = ("Sin revisiones registradas." if count == 0
               else f'{format_count(count)} revisiones registradas.')
    return ('<div class="card"><table class="data"><caption>Registro de riesgos</caption><thead><tr><th>Id</th>'
            '<th>Categoría</th><th>Descripción</th><th>Probabilidad</th><th>Impacto</th><th>Responsable</th>'
            f'<th>Estado</th></tr></thead><tbody>{rows}</tbody></table>'
            f'<p class="note" id="risk-reviews">{reviews}</p></div>')


def _management_view(data: dict) -> str:
    management = data["management"]
    head = f'<section class="view" id="gestion"><h2>{dict(TABS)["gestion"]}</h2>'
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
    return (head + f'<div class="grid">{_cumulative_card(management, data)}{_baseline_card(management["baseline"])}</div>'
            f'{_sprints_table(management)}{hours_note}<div class="grid">{_velocity_table(management)}</div>'
            f'{_risks_table(management)}{hours_gate}</section>')


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
    views = (_summary(data) + _data_view(data) + _trace_view(data) + _models_view(data) + _stress_view(data)
             + _management_view(data) + _pending("entrega", dict(TABS)["entrega"]) + _guided())
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
