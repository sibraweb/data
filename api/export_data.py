"""
Espejo local de las series — se guarda en SIBRA-DATA-CORREGIDO/AUTO/<categoría>/,
NUNCA en RAW/ (esos archivos son los originales armados a mano por Juan,
con sus propias fórmulas y columnas — no se tocan ni se pisan).

Sheets sigue siendo la base "viva" que lee el server (server.py); esta
carpeta AUTO/ es un espejo de solo lectura para otras herramientas, se
pisa entero en cada export.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "SIBRA-DATA-CORREGIDO" / "AUTO"

# tab de SIBRATECH_INDICES -> subcarpeta dentro de AUTO/ (misma taxonomía
# de categorías que ya usa SIBRA-DATA-CORREGIDO/RAW/)
DESTINO = {
    "CER": "INDICES",
    "UVA": "INDICES",
    "DOLAR": "FX",
    "RIPTE": "SALARIOS",
    "UOCRA": "SALARIOS",
    "UOCRA_ADICIONALES": "SALARIOS",
    "CONSTRUCCION": "CONSTRUCCION",
    "REM_IPC": "PREVISIONES",
    "REM_FX": "PREVISIONES",
    "REM_IPC_INTERANUAL": "PREVISIONES",
    "ICL": "INDICES",
    "BADLAR": "SALARIOS",
    "INFLACION_INDEC": "INDICES",
    "UVI": "INDICES",
    "BAIBAR": "SALARIOS",
    "DEPOSITOS_30D": "SALARIOS",
    "ADELANTOS_CTA_CTE": "SALARIOS",
    "PRESTAMOS_PERSONALES": "SALARIOS",
    "TAMAR": "SALARIOS",
    "TIM": "SALARIOS",
    "RIESGO_PAIS": "VARIOS",
    "MERVAL": "VARIOS",
    "CAC": "CONSTRUCCION",
}


def exportar_tab(tab: str, records: list[dict]) -> Path | None:
    subcarpeta = DESTINO.get(tab)
    if not subcarpeta or not records:
        return None

    carpeta = DATA_DIR / subcarpeta
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"{tab}.xlsx"

    # unión de claves de todas las filas (preservando orden de aparición) —
    # no alcanza con las claves de la primera fila sola, algunas series
    # (ej. CAC) tienen filas con distintos subconjuntos de columnas.
    headers: list[str] = []
    for r in records:
        for k in r.keys():
            if k not in headers:
                headers.append(k)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = tab
    ws.append(headers)
    for r in records:
        ws.append([r.get(h, "") for h in headers])
    wb.save(destino)
    return destino
