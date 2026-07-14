"""
TIM — Tasa de Intereses Moratorios (BCRA, CCC art. 768 inc. c), base 03/06/1993.

Serie nueva (arrancó a publicarse el 08/01/2026). No está confirmada en el
endpoint JSON api.bcra.gob.ar/estadisticas — se descarga directo el Excel
oficial (formato .xls viejo, requiere xlrd).
"""

from __future__ import annotations

import io

import requests
import xlrd

URL = "https://www.bcra.gob.ar/archivos/Pdfs/PublicacionesEstadisticas/diar_tim.xls"


def fetch_tim() -> list[dict]:
    r = requests.get(URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    wb = xlrd.open_workbook(file_contents=r.content)
    ws = wb.sheet_by_index(0)

    filas = []
    for row in range(ws.nrows):
        fecha_raw, valor = ws.row_values(row)[:2]
        if not fecha_raw or not isinstance(valor, (int, float)):
            continue
        try:
            d, m, y = fecha_raw.split("/")
            fecha = f"{y}-{m}-{d}"
        except (ValueError, AttributeError):
            continue
        filas.append({"FECHA": fecha, "VALOR": valor})
    return filas


if __name__ == "__main__":
    serie = fetch_tim()
    print(f"TIM: {len(serie)} registros, último: {serie[-1] if serie else None}")
