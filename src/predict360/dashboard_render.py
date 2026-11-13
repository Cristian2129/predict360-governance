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

Trace-this-figure, charts and the stress simulator arrive in B12b; the Data, Models,
Management and Handover views in B12c.

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
from src.predict360.formatting import format_cop_m, format_pct

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
__all__ = ["GUIDED_STEPS", "TABS", "format_cop_m", "format_pct", "render", "write"]   # formatters re-exported


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


def _exposure_card(target: str, rec: dict) -> str:
    return (
        f'<div class="card"><h3>{TARGET_NAMES[target]}</h3>'
        f'<div class="figure" data-figure-id="exposure.{target}.observed_cop_m">{format_cop_m(rec["actual_cop_m"])}</div>'
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


def _comparisons(target: str, evaluations: list) -> str:
    """Point difference next to the paired interval, per model and label, against the rule."""
    rows = ""
    for e in sorted((e for e in evaluations if e["target"] == target and e["status"] == "evaluated"
                     and e["vs_baseline"]), key=lambda e: (e["model_id"], e["label"])):
        vs = e["vs_baseline"]
        text, cls = OUTCOMES[vs["outcome"]]
        rows += (f'<tr data-comparison="{_e(target)}.{_e(e["label"])}.{_e(e["model_id"])}">'
                 f'<td>{_e(e["model_id"])}</td><td>{_e(e["label"])}</td>'
                 f'<td>{format_cop_m(vs["difference_cop_m"])}</td>'
                 f'<td>{format_cop_m(vs["ci_low_cop_m"])} a {format_cop_m(vs["ci_high_cop_m"])}</td>'
                 f'<td><span class="status {cls}">{text}</span></td></tr>')
    if not rows:
        return ""
    return ('<table class="compare"><thead><tr><th>Modelo</th><th>Etiqueta</th>'
            '<th>Diferencia en K</th><th>IC pareado</th><th>Resultado</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def _decisions_card(models: dict) -> str:
    decisions = models["decisions"]
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
                     f'{_comparisons(d["target"], models["evaluations"])}'
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
        f'<div class="grid">{_exposure_card("delinquency", tables["delinquency"])}'
        f'{_exposure_card("churn", tables["churn"])}</div>'
        '<p class="note">Son exposición en riesgo, no pérdida. Las cifras del cliente se concilian en cada corrida.</p>'
        f'<div class="grid">{_gates_card(data["gates"])}{_run_card(data["meta"])}</div>'
        f'<div class="stack">{_decisions_card(data["models"])}</div></section>'
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
    views = _summary(data) + "".join(_pending(t, label) for t, label in TABS[1:]) + _guided()
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
