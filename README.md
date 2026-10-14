# FinBank Predict360 — Governance & Analytical Quality Toolkit (Corte 2: Scrum + XP)

Repositorio oficial de **PCM Analytics** (Paula Gacha, Cristian Vega, Marco Jimenez) para la ejecución de los **Sprints 1 y 2** del proyecto **FinBank Predict360** en la asignatura *Gestión, Metodologías Ágiles y Capstone (GMAC)*.

## 1. Propósito del Incremento
Siguiendo el alcance aprobado en el *Project Charter* ("We govern by exposure and close by evidence"), este repositorio implementa el kit de herramientas reproducibles en Python para:
- **`exposure.py` (US-02):** Ordenar el Product Backlog por exposición financiera cuantificada (COP 58,800M en Mora Temprana antes que COP 18,200M en Churn; el resto se marca como *enabling*).
- **`quality.py` (US-03):** Auditar cada fuente de datos contra sus umbrales de calidad (valores nulos, scores fuera de rango, tipos de datos) devolviendo estado *pass/fail*.
- **`sprint_metrics.py` (US-06):** Leer `docs/sprint_log.csv`, calcular Velocidad y Burndown, y generar los gráficos oficiales del reporte.
- **`reconcile.py` (US-04):** Verificar que la cartera sintética reconcilia los COP 58,800M de exposición dentro de la tolerancia definida.

> **Aviso de Datos Sintéticos (Ley 1581/2012):** Este repositorio es público. Todos los archivos en `data/synthetic/` son generados con semilla fija mediante `make_synthetic.py` y no contienen datos personales reales de clientes de FinBank S.A.

## 2. Reglas de Trabajo del Equipo (Scrum + XP)
- **`main` protegida:** Todo cambio entra por *Pull Request (PR)* con al menos **1 aprobación**, y ningún autor aprueba su propio PR.
- **Convención de ramas:** `feature/us-XX-nombre-corto` o `refactor/nombre-corto`.
- **Historial TDD:** Primero se realiza el commit `test:` (prueba que falla), luego `feat:` (implementación que pasa en verde) y finalmente `refactor:` cuando aplica.
- **Pair Programming:** Se registra con evidencia en `docs/xp_log.md` y mediante el tráiler `Co-authored-by:` en el mensaje del commit.
- **Definition of Done (DoD):** Criterios de aceptación cumplidos al 100%, evidencia adjunta en Trello y `docs/evidence/`, pruebas `pytest` en verde, PR aprobado e incremento presentado en el *Sprint Review*.

## 3. Ejecución Local
```bash
pip install -r requirements.txt
python src/predict360/make_synthetic.py
PYTHONPATH=. pytest tests/ -v
python src/predict360/sprint_metrics.py