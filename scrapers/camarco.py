"""
CAMARCO / Índice CAC — "Indicador de la Variación del Costo de un Edificio
Tipo en Capital Federal".

La fuente oficial (camarco.org.ar) tiene el reporte completo detrás de un
login de socios — solo el número del mes corriente es público.

Se usa la API pública de iKiwi.net.ar (https://ikiwi.net.ar/indice-cac/,
detrás de escena llama a `prestamos.ikiwi.net.ar/api/cacs`) — JSON limpio,
sin login, con el nivel del índice (no solo la variación %) para las 3
series (general/materiales/mano de obra), actualizado mes a mes. Se
descubrió leyendo el JS de la página (`apiCac.js`, define el endpoint).

Antes se usaba un CSV de cifrasonline.com.ar (Google Sheets público) que
también funciona pero requería parsear tríos de filas por período y tenía
un bug de la fuente (setiembre abreviado distinto) — esta API es más
simple y llega más al día. Si en el futuro este endpoint deja de andar,
volver a https://ikiwi.net.ar/indice-cac/ e inspeccionar sus JS.
"""

from __future__ import annotations

import calendar
import datetime as dt

import requests

API_URL = "https://prestamos.ikiwi.net.ar/api/cacs"


def _fin_de_mes(periodo_iso: str) -> str:
    """'2026-05-01' -> '2026-05-31' — mismo criterio de "fecha vigente a fin
    de mes" que el resto del proyecto (APYMECO/IPC ya lo usaban)."""
    fecha = dt.date.fromisoformat(periodo_iso)
    ultimo_dia = calendar.monthrange(fecha.year, fecha.month)[1]
    return fecha.replace(day=ultimo_dia).isoformat()


def fetch_cac() -> list[dict]:
    """Devuelve una fila por período: {FECHA, COSTO_CONSTRUCCION, MATERIALES, MANO_DE_OBRA}
    (índice base 100 = dic-2014)."""
    r = requests.get(API_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    datos = r.json()

    filas = []
    for fila in datos:
        if not fila.get("period"):
            continue
        filas.append({
            "FECHA": _fin_de_mes(fila["period"]),
            "COSTO_CONSTRUCCION": fila.get("general"),
            "MATERIALES": fila.get("materials"),
            "MANO_DE_OBRA": fila.get("labour_force"),
        })

    return sorted(filas, key=lambda r: r["FECHA"])


if __name__ == "__main__":
    serie = fetch_cac()
    print(f"CAC: {len(serie)} períodos, último: {serie[-1] if serie else None}")
