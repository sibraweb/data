"""
Seed histórico de materiales puntuales, del Excel de Juan (hoja "MAT R12" =
Cerámica Norte). Va a una hoja propia MATERIALES_HISTORICO — NUNCA se mezcla
con COTIZACIONES (que es de sibra-obra-repo, no se toca) — y en tiempo de
consulta el backend superpone este histórico con lo que venga de
COTIZACIONES para el mismo (proveedor, material).

Uso:
    cd api
    python migrar_materiales_historico.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sheets

MESES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}

HEADERS = ["CLAVE", "ID_PROVEEDOR", "DESCRIPCION", "FECHA", "PRECIO"]

# Cerámica Norte (ID 43) — hoja "MAT R12" del Excel de Juan. Nombres de
# columna del Excel -> DESCRIPCION real usada en COTIZACIONES (para que se
# superpongan como una sola serie).
CERAMICA_NORTE = "43"
COLUMNAS = {
    "cemento": "CEMENTO PORTLAND X 25 KG. (LOMA NEGRA)-25",
    "hierro": "HIERRO Aº TORS.Ø 10-BR X 12MT.",
    "ladrillo": "LADRILLO HUECO DE 1º 18X18X25-5",
}

# (mes-año, cemento, hierro_10mm, ladrillo) — tal cual la tabla que pasó Juan
DATOS_R12 = [
    ("nov-18", 160.70, 367.52, 16.16),
    ("feb-19", 158.40, 404.04, 16.05),
    ("ago-20", 298.44, 884.19, 49.00),
    ("sep-20", 316.81, 1083.09, 65.07),
    ("ene-21", 335.17, 1539.24, 58.95),
    ("abr-21", 371.90, 1650.63, 59.23),
    ("may-21", 385.68, 1650.63, 59.23),
    ("jun-21", 385.68, 1483.55, 59.23),
    ("jul-21", 385.68, 1535.48, 59.23),
    ("sep-21", 394.86, 1644.50, 59.23),
    ("oct-21", 408.63, 1644.50, 59.23),
    ("feb-22", 445.37, 1702.48, 61.01),
    ("abr-22", 477.50, 1851.42, 61.01),
    ("may-22", 505.05, 1925.48, 65.89),
    ("jun-22", 587.70, 2106.31, 74.01),
    ("ago-22", 697.89, 2629.77, 101.68),
    ("mar-23", 1115.00, 3190.34, 141.21),
    ("may-23", 1444.45, 4063.02, 164.27),
    ("jun-23", 1566.67, 4469.32, 200.88),
    ("jul-23", 1683.34, 4834.02, 220.97),
    ("ago-23", 1777.78, 5583.29, 220.00),
    ("sep-23", 2444.44, 7044.81, 212.43),
    ("oct-23", 2666.67, 7044.81, 233.67),
    ("nov-23", 2988.50, 11988.00, 249.28),
    ("dic-23", 2666.67, 10798.35, 299.14),
    ("ene-24", 4000.00, 15166.73, 373.95),
    ("feb-24", 4916.67, 15014.83, 391.60),
    ("mar-24", 5555.56, 15014.83, 450.00),
    ("abr-24", 6305.56, 15014.83, 450.34),
    ("may-24", 6000.00, 14398.00, 450.34),
    ("jun-24", 6444.45, 14398.91, 480.57),
    ("jul-24", 6444.45, 14237.65, 480.57),
    ("ago-24", 6444.45, 14664.78, 504.60),
    ("nov-24", 5888.89, 14664.78, 529.83),
    ("feb-25", 5750.00, 14245.79, 586.42),
    ("abr-25", 6333.34, 15398.02, 557.78),
    ("ago-25", 7222.22, 16311.88, 567.38),
    ("ene-26", 8333.33, 15946.00, 619.58),
    ("mar-26", 8333.33, 15946.09, 635.06),
]


def _fecha(mes_anio: str) -> str:
    mes, anio = mes_anio.split("-")
    return f"20{anio}-{MESES[mes]:02d}-01"


def construir_filas() -> list[dict]:
    filas = []
    for mes_anio, cemento, hierro, ladrillo in DATOS_R12:
        fecha = _fecha(mes_anio)
        for clave_col, precio in (("cemento", cemento), ("hierro", hierro), ("ladrillo", ladrillo)):
            descripcion = COLUMNAS[clave_col]
            filas.append({
                "CLAVE": f"{CERAMICA_NORTE}|{descripcion}|{fecha}",
                "ID_PROVEEDOR": CERAMICA_NORTE,
                "DESCRIPCION": descripcion,
                "FECHA": fecha,
                "PRECIO": precio,
            })
    return filas


def main():
    sid = sheets.INDICES_SHEET_ID or sheets.ensure_indices_sheet()
    filas = construir_filas()
    n = sheets.upsert_series(sid, "MATERIALES_HISTORICO", HEADERS, "CLAVE", filas)
    print(f"MATERIALES_HISTORICO -> {n} filas nuevas de {len(filas)} totales "
          f"({len(DATOS_R12)} meses x 3 materiales, Cerámica Norte)")


if __name__ == "__main__":
    main()
