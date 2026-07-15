"""
Backfill puntual: la migración inicial (migrar_historico.py) sólo trajo
histórico de dólar oficial hasta 2025-02-28 (columna "Monto en $" de
USD.xlsx), y el scheduler recién empezó a scrapear a diario desde que este
módulo arrancó — dejando un hueco real entre esas dos fechas. Rellena ese
hueco con argentinadatos.py (oficial/blue/mayorista desde 2011).

Uso: python backfill_dolar.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sheets
from scrapers import argentinadatos

DOLAR_TAB = "DOLAR"
DOLAR_HEADERS = ["FECHA", "OFICIAL_COMPRA", "OFICIAL_VENTA", "BLUE_COMPRA", "BLUE_VENTA",
                 "MEP_COMPRA", "MEP_VENTA", "CCL_COMPRA", "CCL_VENTA",
                 "MAYORISTA_COMPRA", "MAYORISTA_VENTA", "CRIPTO_COMPRA", "CRIPTO_VENTA",
                 "TARJETA_COMPRA", "TARJETA_VENTA"]

CASA_A_COLUMNAS = {
    "oficial": ("OFICIAL_COMPRA", "OFICIAL_VENTA"),
    "blue": ("BLUE_COMPRA", "BLUE_VENTA"),
    "mayorista": ("MAYORISTA_COMPRA", "MAYORISTA_VENTA"),
}


def main():
    sid = sheets.INDICES_SHEET_ID or sheets.ensure_indices_sheet()

    existentes = sheets.read_records(sid, DOLAR_TAB)
    fechas_existentes = {r["FECHA"] for r in existentes}
    print(f"DOLAR ya tiene {len(existentes)} filas (rango {min(fechas_existentes)} a {max(fechas_existentes)})")

    crudo = argentinadatos.fetch_dolares_historico()
    por_fecha: dict[str, dict] = {}
    for fila in crudo:
        casa = fila.get("casa")
        cols = CASA_A_COLUMNAS.get(casa)
        if not cols:
            continue
        fecha = fila["fecha"]
        registro = por_fecha.setdefault(fecha, {"FECHA": fecha})
        registro[cols[0]] = fila.get("compra")
        registro[cols[1]] = fila.get("venta")

    nuevas = [reg for fecha, reg in por_fecha.items() if fecha not in fechas_existentes]
    nuevas.sort(key=lambda r: r["FECHA"])
    print(f"argentinadatos trae {len(por_fecha)} fechas en total, {len(nuevas)} son nuevas para nosotros")

    if nuevas:
        n = sheets.upsert_series(sid, DOLAR_TAB, DOLAR_HEADERS, "FECHA", nuevas)
        print(f"Insertadas {n} filas nuevas en DOLAR (rango {nuevas[0]['FECHA']} a {nuevas[-1]['FECHA']})")
    else:
        print("Nada para insertar.")


if __name__ == "__main__":
    main()
