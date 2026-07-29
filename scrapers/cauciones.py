# -*- coding: utf-8 -*-
"""Cauciones en pesos (mercado BYMA) — tasa de referencia por plazo.

API pública open.bymadata.com.ar, sin auth (verificado 2026-07-28 desde
`Vinculacion bancos/servicio/financiamiento.py`, mismo fetch portado acá
para que quede en el pipeline de scrapers de indices — series históricas,
mismo patrón que `dolares.py`). Las tasas vienen como fracción (0.162 =
16,2% TNA); se persisten como % (16.2).
"""
from __future__ import annotations

import requests
import urllib3

urllib3.disable_warnings()

URL = "https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free/cauciones"

# Plazos de referencia que se guardan como columnas fijas de la serie
# (la curva completa tiene ~83 plazos — para histórico alcanza con estos,
# mismos default que ya usaba financiamiento.texto_cauciones()).
PLAZOS_REFERENCIA = {"TASA_1D": 1, "TASA_7D": 7, "TASA_14D": 14, "TASA_30D": 30}


def _pct(x):
    try:
        return round(float(x) * 100, 2) if x else None
    except (TypeError, ValueError):
        return None


def _curva() -> list[dict]:
    """[{plazo_dias, tasa}] en pesos, ordenada por plazo. [] si BYMA no responde."""
    try:
        r = requests.post(
            URL, json={"excludeZeroPxAndQty": False, "T2": True, "T1": False, "T0": False},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=25, verify=False)
        data = r.json()
        lista = data if isinstance(data, list) else data.get("data", [])
    except Exception:
        return []
    curva = []
    for x in lista:
        if "PESOS" not in str(x.get("symbol", "")).upper():
            continue
        tasa = _pct(x.get("trade")) or _pct(x.get("previousClosingPrice"))
        plazo = x.get("daysToMaturity")
        if tasa is None or plazo is None:
            continue
        curva.append({"plazo_dias": plazo, "tasa": tasa})
    curva.sort(key=lambda c: c["plazo_dias"])
    return curva


def fetch_actual() -> dict:
    """{"FECHA": "YYYY-MM-DD", "TASA_1D":.., "TASA_7D":.., ...} — la tasa más
    cercana a cada plazo de referencia. Columnas en None si BYMA no respondió
    (upsert_valores_ancha_bulk ya ignora columnas None, no pisa lo que hay)."""
    import datetime as dt

    curva = _curva()
    fila: dict = {"FECHA": dt.date.today().isoformat()}
    for col, plazo in PLAZOS_REFERENCIA.items():
        fila[col] = min(curva, key=lambda c: abs(c["plazo_dias"] - plazo))["tasa"] if curva else None
    return fila


if __name__ == "__main__":
    print(fetch_actual())
