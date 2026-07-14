"""
REM — Relevamiento de Expectativas de Mercado (BCRA).

Encuesta mensual a ~40 consultoras/bancos con previsiones de inflación,
tipo de cambio, tasa, PIB, etc. Se publica como UN ÚNICO Excel que se
pisa cada mes con el historial completo (no hay API ni paginación:
se descarga el archivo entero y se filtra).

Fuente: https://www.bcra.gob.ar/PublicacionesEstadisticas/Relevamiento_Expectativas_de_Mercado.asp
Archivo: historico-relevamiento-expectativas-mercado.xlsx (hoja "Base de Datos Completa")
"""

from __future__ import annotations

import io

import openpyxl
import requests

URL = (
    "https://www.bcra.gob.ar/archivos/Pdfs/PublicacionesEstadisticas/"
    "informes/historico-relevamiento-expectativas-mercado.xlsx"
)

# (Variable, Referencia) tal como aparecen en la hoja "Base de Datos Completa"
VARIABLES = {
    "ipc": ("Precios minoristas (IPC nivel general; INDEC)", "var. % mensual"),
    "fx": ("Tipo de cambio nominal", "$/USD"),
}


def _descargar() -> openpyxl.Workbook:
    r = requests.get(URL, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True)


def fetch_rem() -> dict[str, list[dict]]:
    """Devuelve {"ipc": [...], "fx": [...]}, cada fila:
    {FECHA_PRONOSTICO, PERIODO, MEDIANA, PROMEDIO, DESVIO, MAXIMO, MINIMO, PERCENTIL_90}"""
    wb = _descargar()
    ws = wb["Base de Datos Completa"]

    resultado: dict[str, list[dict]] = {"ipc": [], "fx": []}
    objetivo = {v: k for k, v in VARIABLES.items()}

    for row in ws.iter_rows(min_row=3, values_only=True):
        fecha_pron = row[0]
        if fecha_pron is None:
            continue
        variable, referencia = row[1], row[2]
        clave = objetivo.get((variable, referencia))
        if not clave:
            continue
        periodo, mediana, promedio, desvio, maximo, minimo, p90 = row[3:10]
        resultado[clave].append({
            "FECHA_PRONOSTICO": fecha_pron.date().isoformat(),
            "PERIODO": periodo.date().isoformat() if hasattr(periodo, "date") else periodo,
            "MEDIANA": mediana,
            "PROMEDIO": promedio,
            "DESVIO": desvio,
            "MAXIMO": maximo,
            "MINIMO": minimo,
            "PERCENTIL_90": p90,
        })
    return resultado


if __name__ == "__main__":
    datos = fetch_rem()
    for k, filas in datos.items():
        print(f"{k}: {len(filas)} filas, última: {filas[-1] if filas else None}")
