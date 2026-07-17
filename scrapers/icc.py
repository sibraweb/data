"""
ICC — Índice de Costo de la Construcción, por provincia (iKiwi.net.ar).

Distinto del CAMARCO/CAC (que es un único índice para Capital Federal): el
ICC tiene una serie propia por provincia y un componente que CAC no tiene,
"Gastos" (además de general/materiales/mano de obra). Fuente pública, sin
login: https://prestamos.ikiwi.net.ar/api/iccs (mismo backend que /api/cacs,
descubierto igual leyendo el JS de https://ikiwi.net.ar/indice-costo-construccion/<provincia>/).

Cubre CABA, Buenos Aires, Córdoba y Santa Fe, base ene-2015=100 (o similar,
no está documentado el mes base exacto), mensual.
"""

from __future__ import annotations

import calendar
import datetime as dt

import requests

API_URL = "https://prestamos.ikiwi.net.ar/api/iccs"

# Nombre de provincia en la API -> nombre de pestaña (sin espacios/acentos).
PROVINCIAS = {
    "CABA": "CABA",
    "Buenos Aires": "BUENOS_AIRES",
    "Córdoba": "CORDOBA",
    "Santa Fe": "SANTA_FE",
}


def _fin_de_mes(periodo_iso: str) -> str:
    fecha = dt.date.fromisoformat(periodo_iso)
    ultimo_dia = calendar.monthrange(fecha.year, fecha.month)[1]
    return fecha.replace(day=ultimo_dia).isoformat()


def _numero(valor) -> float | None:
    if valor is None or valor == "":
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def fetch_icc() -> dict[str, list[dict]]:
    """Devuelve {clave_provincia: [{FECHA, GENERAL, MATERIALES, MANO_DE_OBRA, GASTOS}, ...]}."""
    r = requests.get(API_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    datos = r.json()

    por_provincia: dict[str, list[dict]] = {clave: [] for clave in PROVINCIAS.values()}
    for fila in datos:
        provincia = fila.get("province")
        clave = PROVINCIAS.get(provincia)
        if not clave or not fila.get("period"):
            continue
        por_provincia[clave].append({
            "FECHA": _fin_de_mes(fila["period"]),
            "GENERAL": _numero(fila.get("general")),
            "MATERIALES": _numero(fila.get("materials")),
            "MANO_DE_OBRA": _numero(fila.get("labour_force")),
            "GASTOS": _numero(fila.get("expenses")),
        })

    for clave in por_provincia:
        por_provincia[clave].sort(key=lambda r: r["FECHA"])

    return por_provincia


if __name__ == "__main__":
    resultado = fetch_icc()
    for clave, serie in resultado.items():
        print(f"{clave}: {len(serie)} períodos, último: {serie[-1] if serie else None}")
