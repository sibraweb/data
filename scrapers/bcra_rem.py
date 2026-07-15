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
import re

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

# Interanual (i.a.) a CUALQUIER mes objetivo, no solo diciembre — el REM
# publica "var. % i.a.; dic-26/27/28" (año calendario completo, dic/dic)
# PERO TAMBIÉN "var. % i.a.; jun-27", "jun-28" (12 y 24 meses hacia adelante
# desde una encuesta de junio) — esos son los anclajes intermedios que arman
# una cadena semestral (dic-26, jun-27, dic-27, jun-28, dic-28...) en vez de
# saltar de golpe año a año. Se capturan todos, sin asumir el mes.
IPC_INTERANUAL_VARIABLE = "Precios minoristas (IPC nivel general; INDEC)"
IPC_INTERANUAL_REGEX = re.compile(r"^var\. % i\.a\.; ([a-z]{3})-(\d{2})$")
MESES_ABREV = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def _descargar() -> openpyxl.Workbook:
    r = requests.get(URL, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True)


def fetch_rem() -> dict[str, list[dict]]:
    """Devuelve {"ipc": [...], "fx": [...], "ipc_interanual": [...]}.
    ipc/fx: {FECHA_PRONOSTICO, PERIODO, MEDIANA, PROMEDIO, DESVIO, MAXIMO, MINIMO, PERCENTIL_90}
    ipc_interanual: ídem, pero PERIODO es el mes objetivo del interanual
    (dic de cada año = año calendario completo; otros meses = 12/24 meses
    hacia adelante desde la fecha de la encuesta)."""
    wb = _descargar()
    ws = wb["Base de Datos Completa"]

    resultado: dict[str, list[dict]] = {"ipc": [], "fx": [], "ipc_interanual": []}
    objetivo = {v: k for k, v in VARIABLES.items()}

    for row in ws.iter_rows(min_row=3, values_only=True):
        fecha_pron = row[0]
        if fecha_pron is None:
            continue
        variable, referencia = row[1], row[2]
        periodo, mediana, promedio, desvio, maximo, minimo, p90 = row[3:10]

        clave = objetivo.get((variable, referencia))
        if clave:
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
            continue

        if variable == IPC_INTERANUAL_VARIABLE and referencia:
            m = IPC_INTERANUAL_REGEX.match(str(referencia))
            if m:
                mes = MESES_ABREV.get(m.group(1))
                if mes:
                    anio = 2000 + int(m.group(2))
                    resultado["ipc_interanual"].append({
                        "FECHA_PRONOSTICO": fecha_pron.date().isoformat(),
                        "PERIODO": f"{anio:04d}-{mes:02d}-01",
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
