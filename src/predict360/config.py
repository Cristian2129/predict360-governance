"""Loads run configuration, data contracts and project assumptions.

The system travels, the data does not: switching from ``synthetic.yaml`` to
``real.yaml`` must be the only change needed to run inside FinBank. This module
only loads and checks the *shape* of those files; Gate 1 rules live in
``quality.py``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
CONTRACTS_DIR = CONFIG_DIR / "contracts"

REQUIRED_CONFIG_KEYS = (
    "synthetic",
    "seed",
    "snapshot_date",
    "paths",
    "hmac",
    "reconciliation",
    "horizons_days",
    "retention_days",
    "generator",
)


def _read_yaml(path: str | Path) -> Any:
    path = Path(path)
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_config(path: str | Path) -> dict:
    """Loads a run configuration and fails fast if a required key is missing."""
    cfg = _read_yaml(path)
    if not isinstance(cfg, dict):
        raise ValueError(f"{path}: configuration must be a mapping")
    missing = [key for key in REQUIRED_CONFIG_KEYS if key not in cfg]
    if missing:
        raise ValueError(f"{path}: missing required keys: {', '.join(missing)}")
    if not isinstance(cfg["synthetic"], bool):
        raise ValueError(f"{path}: 'synthetic' must be true or false")
    hmac_cfg = cfg["hmac"] or {}
    if "key_env" not in hmac_cfg:
        raise ValueError(f"{path}: missing required key hmac.key_env")
    if not cfg["synthetic"] and "demo_key" in hmac_cfg:
        raise ValueError(f"{path}: hmac.demo_key is only allowed when synthetic is true")
    if cfg["synthetic"] and not isinstance(cfg["generator"], dict):
        raise ValueError(f"{path}: a synthetic config needs a 'generator' section")
    return cfg


def load_assumptions(path: str | Path = CONFIG_DIR / "assumptions.yaml") -> dict:
    """Returns ``{"items": [...], "values": nested dict}``.

    Each item's ``value`` maps dotted keys (``value.action_effectiveness``) to
    values; ``values`` merges them into a nested dict for easy lookup.
    """
    data = _read_yaml(path)
    items = data.get("assumptions") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError(f"{path}: expected an 'assumptions' list")
    values: dict = {}
    for item in items:
        for dotted, value in (item.get("value") or {}).items():
            node = values
            *parents, leaf = dotted.split(".")
            for part in parents:
                node = node.setdefault(part, {})
            node[leaf] = value
    return {"version": data.get("version"), "items": items, "values": values}


def load_contract(name: str, contracts_dir: str | Path = CONTRACTS_DIR) -> dict:
    """Loads ``<contracts_dir>/<name>.yaml`` (e.g. ``delinquency_v1``)."""
    path = Path(contracts_dir) / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Unknown contract: {name} ({path})")
    contract = _read_yaml(path)
    if "columns" not in contract and "fields" not in contract:
        raise ValueError(f"{path}: contract needs 'columns' or 'fields'")
    return contract


def contract_columns(name: str, contracts_dir: str | Path = CONTRACTS_DIR) -> list[str]:
    """Column (or field) names of a contract, in declared order."""
    contract = load_contract(name, contracts_dir)
    return list(contract.get("columns") or contract.get("fields"))
