"""
Índice de Salarios (IS) de INDEC — evolución de salarios sin estacionalidad
(no incluye horas extra, ausentismo, presentismo, premios, etc.), por
sector: privado registrado, privado no registrado, público, y el total.

Fuente oficial, CSV público sin login (base oct-2016=100):
https://www.indec.gob.ar/ftp/cuadros/sociedad/indice_salarios.csv

Formato: separador ";", decimal ",", fecha "D/M/AAAA" (siempre día 1).
El sector no registrado se estima vía EPH (no es relevamiento directo) y
solo tiene datos desde que INDEC empezó a publicarlo — las filas viejas
(2015-2016) vienen con "NA" en varias columnas, se descartan esos campos
puntuales sin descartar la fila entera.
"""

from __future__ import annotations

import calendar
import csv
import datetime as dt
import io

import requests

URL = "https://www.indec.gob.ar/ftp/cuadros/sociedad/indice_salarios.csv"

COLUMNAS = {
    "IS_sector_privado_registrado": "PRIVADO_REGISTRADO",
    "IS_sector_publico": "PUBLICO",
    "IS_total_registrado": "TOTAL_REGISTRADO",
    "IS_sector_no_registrado": "NO_REGISTRADO",
    "IS_indice_total": "INDICE_TOTAL",
}


def _numero_ar(valor: str) -> float | None:
    valor = valor.strip()
    if not valor or valor.upper() == "NA":
        return None
    try:
        return float(valor.replace(",", "."))
    except ValueError:
        return None


def _fecha_iso(periodo: str) -> str | None:
    """'1/10/2015' -> '2015-10-31' (fin de mes, mismo criterio que el resto
    de las series mensuales del proyecto — INDEC siempre publica día 1)."""
    partes = periodo.strip().split("/")
    if len(partes) != 3:
        return None
    dia, mes, anio = partes
    try:
        anio, mes = int(anio), int(mes)
        ultimo_dia = calendar.monthrange(anio, mes)[1]
        return dt.date(anio, mes, ultimo_dia).isoformat()
    except ValueError:
        return None


def fetch_salarios() -> list[dict]:
    """Devuelve una fila por mes: {FECHA, PRIVADO_REGISTRADO, PUBLICO,
    TOTAL_REGISTRADO, NO_REGISTRADO, INDICE_TOTAL} (índice base oct-2016=100)."""
    r = requests.get(URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    lector = csv.DictReader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";")

    filas = []
    for fila_csv in lector:
        fecha = _fecha_iso(fila_csv.get("periodo", ""))
        if not fecha:
            continue
        fila = {"FECHA": fecha}
        for col_origen, col_destino in COLUMNAS.items():
            valor = _numero_ar(fila_csv.get(col_origen, ""))
            if valor is not None:
                fila[col_destino] = valor
        filas.append(fila)

    return sorted(filas, key=lambda r: r["FECHA"])


if __name__ == "__main__":
    serie = fetch_salarios()
    print(f"Salarios INDEC: {len(serie)} períodos, último: {serie[-1] if serie else None}")
