"""Indicador Vial de CAMARCO → `series_valores` (serie CAMARCO_VIAL).

Costo de una obra vial tipo (40 km, 7,20 m de calzada), dic-01 = 100.
Dos columnas, como lo publica CAMARCO:
  SIN_GF  sin gastos financieros
  CON_GF  con gastos financieros (BADLAR; +10 pp para no MiPyME desde 15/03/21)

⚠ El encabezado del PDF dice «Base 100 = Nov '01» pero la primera fila de la
tabla es dic-01 = 100. Se respeta la tabla.
⚠ Los 3 últimos meses salen marcados (*) Provisorios: se registran en
`series_provisorios` igual que el CAC, para que un certificado liquidado con
un provisorio no pierda el número si CAMARCO lo revisa.
Fecha = último día del mes, como el CAC.

Fuente: camarco.org.ar/wp-content/uploads/AAAA/MM/Evolucion-Indicador-Vial-<Mes>-<año>.pdf
CSV: indices/datos/camarco_vial/indicador_vial_camarco.csv (periodo,sin_gf,con_gf)

    py api/cargar_camarco_vial.py 2026-06 2026-07 2026-08   # los provisorios
"""
import calendar
import csv
import sys
from pathlib import Path
from dotenv import load_dotenv

RAIZ = Path(__file__).parent.parent
load_dotenv(RAIZ / ".env")
import db  # noqa: E402

SERIE = "CAMARCO_VIAL"
CSV = RAIZ / "datos" / "camarco_vial" / "indicador_vial_camarco.csv"


def _fin_de_mes(periodo):
    a, m = map(int, periodo.split("-"))
    return f"{a:04d}-{m:02d}-{calendar.monthrange(a, m)[1]:02d}"


if __name__ == "__main__":
    provisorios = set(sys.argv[1:])
    filas = []
    with open(CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            filas.append({"FECHA": _fin_de_mes(r["periodo"]),
                          "SIN_GF": r["sin_gf"], "CON_GF": r["con_gf"],
                          "_periodo": r["periodo"]})
    n = db.upsert_valores_ancha_bulk(SERIE, filas, ["SIN_GF", "CON_GF"])
    print(f"{SERIE}: {len(filas)} meses leídos, {n} valores nuevos")
    if provisorios:
        flags = [{"FECHA": f["FECHA"], "PROVISORIO": f["_periodo"] in provisorios}
                 for f in filas]
        print("provisorios:", db.guardar_provisorios(SERIE, flags))
