"""
ArgentinaDatos (api.argentinadatos.com) — API pública/gratuita comunitaria.

Se usa acá solo para lo que no tenemos por otro lado: riesgo país (no lo
publica el BCRA). También expone dólar oficial/blue/mayorista desde 2011,
por si hace falta backfill histórico del blue (no lo tenemos de otra fuente).
"""

from __future__ import annotations

import requests

BASE_URL = "https://api.argentinadatos.com/v1"


def fetch_riesgo_pais() -> list[dict]:
    r = requests.get(f"{BASE_URL}/finanzas/indices/riesgo-pais", timeout=30)
    r.raise_for_status()
    return [{"FECHA": f["fecha"], "VALOR": f["valor"]} for f in r.json()]


def fetch_dolares_historico() -> list[dict]:
    """Histórico diario de oficial/blue/mayorista desde 2011 (dolarapi.com solo da el valor de hoy)."""
    r = requests.get(f"{BASE_URL}/cotizaciones/dolares", timeout=30)
    r.raise_for_status()
    return r.json()  # [{"casa": "oficial"|"blue"|"mayorista", "compra", "venta", "fecha"}, ...]


if __name__ == "__main__":
    rp = fetch_riesgo_pais()
    print(f"Riesgo país: {len(rp)} registros, último: {rp[-1] if rp else None}")
    dh = fetch_dolares_historico()
    print(f"Dólares histórico: {len(dh)} registros, último: {dh[-1] if dh else None}")
