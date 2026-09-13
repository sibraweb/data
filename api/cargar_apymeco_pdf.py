# -*- coding: utf-8 -*-
"""Carga el informe mensual de APYMECO (PDF) con las CUATRO columnas.

    py api/cargar_apymeco_pdf.py "ÍNDICE APYMECO AGOSTO 2026.pdf"
    py api/cargar_apymeco_pdf.py informe.pdf --solo-leer   # no escribe

⚠ POR QUE HACE FALTA ESTE SCRIPT Y NO ALCANZA EL SCRAPER. La pagina
(`indice.php`) publica el indice general y el $/m2 de los ultimos 13 meses, y de
eso se ocupa `refrescar_apymeco` en la cadena diaria. La apertura —MANO DE OBRA,
MATERIALES y PROVISIONES DE 3ROS— **solo esta en el informe mensual en PDF**, y
sus URLs viven en `_temp/` con nombres de sesion que contestan 404 apenas se
reusan. Juan (13/09/2026) pasa el informe cada tanto y esto lo carga.

⚠ EL ORDEN DE COLUMNAS SE VERIFICA CONTRA LA BASE, no se asume. El encabezado
del PDF sale desarmado de pdfplumber, asi que antes de escribir se comparan los
meses que ya estaban cargados. Si no coinciden, NO carga: seria pegar mano de
obra en la columna de materiales, un error que no revienta y solo miente.

⚠ Y SE IMPRIME LA DIFERENCIA CUANDO EL PDF CORRIGE UN VALOR. Medido el
13/09/2026: jun-26 vale 14.896,76 en la pagina y 14.897,21 en el informe del 8
de septiembre. El upsert del proyecto es append-only (no pisa lo cargado), asi
que la diferencia se avisa en vez de resolverse sola.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE.parent / "scrapers"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BASE.parent / ".env")

import apymeco  # noqa: E402
import db  # noqa: E402

SERIE = "APYMECO"
COLUMNAS = ["INDICE_GENERAL", "MATERIALES", "MANO_DE_OBRA", "PROVISIONES"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--solo-leer", action="store_true")
    # ⚠ EL MODO SEGURO, y hubo que agregarlo por un caso real. Medido el
    # 13/09/2026: el Excel historico traia mal INDICE_GENERAL en 2023 y 2024
    # (12 de 12 meses cada anio) y MATERIALES/PROVISIONES en parte de 2022,
    # mientras MANO_DE_OBRA coincide siempre — o sea que el mapeo de columnas
    # esta bien y lo que esta mal son los valores viejos. Con --solo-faltantes
    # se carga unicamente lo que la base NO tiene, sin tocar lo cargado, que es
    # la regla append-only del proyecto. Corregir los 52 valores viejos es otra
    # decision y la tiene que tomar una persona.
    ap.add_argument("--solo-faltantes", action="store_true")
    # ⚠ PISA LO CARGADO. Se uso el 13/09/2026 por decision de Juan («corregimos
    # todo con este archivo») despues de probar que APYMECO NO revisa su
    # indice: cuatro informes entre 2020 y 2026, 73 meses solapados, cero
    # diferencias. O sea que los 52 valores que discrepaban eran del Excel
    # historico, no correcciones de la camara. Cada valor pisado queda en
    # `series_correcciones` con el anterior, el nuevo y de que informe salio.
    ap.add_argument("--corregir", action="store_true")
    args = ap.parse_args()

    filas = apymeco.fetch_apymeco_pdf(args.pdf)
    if not filas:
        print("El PDF no trae la tabla «Resumen indice». ¿Es el informe mensual?")
        return 1
    print("%d meses en el informe: %s -> %s"
          % (len(filas), filas[0]["FECHA"], filas[-1]["FECHA"]))

    # ── el control de columnas, antes de escribir ──────────────────────────
    base = {x["FECHA"]: x for x in db.leer_serie_ancha(SERIE)}
    comunes = [f for f in filas if f["FECHA"] in base]
    cotejados, difieren = 0, []
    for f in comunes:
        b = base[f["FECHA"]]
        for col in COLUMNAS:
            viejo, nuevo = b.get(col), f.get(col)
            if viejo in (None, "") or nuevo is None:
                continue
            cotejados += 1
            if abs(float(viejo) - float(nuevo)) > 0.01:
                difieren.append((f["FECHA"], col, float(viejo), float(nuevo)))

    print("control: %d valores cotejados contra la base, %d difieren"
          % (cotejados, len(difieren)))
    for fecha, col, viejo, nuevo in difieren[:12]:
        print("   %s %-16s base %12.2f   PDF %12.2f   (%+.2f)"
              % (fecha, col, viejo, nuevo, nuevo - viejo))

    # ⚠ el umbral es por PROPORCION, no por cantidad: un par de correcciones de
    # centavos es normal, pero si difiere mas de la decima parte de lo cotejado
    # es que las columnas estan cruzadas.
    if args.corregir:
        if args.solo_leer:
            print("\n--solo-leer: no se escribio nada.")
            return 0
        r = db.corregir_valores_ancha(
            SERIE, filas, COLUMNAS,
            fuente=Path(args.pdf).name,
            motivo="El Excel historico (CONST_2.xlsx) traia valores equivocados. "
                   "APYMECO no revisa su indice: 4 informes 2020-2026, 73 meses "
                   "solapados, 0 diferencias.")
        print("\ncorregidos %d · nuevos %d · ya iguales %d"
              % (r["corregidos"], r["nuevos"], r["iguales"]))
        print("cada valor pisado quedo en `series_correcciones` con el anterior.")
        return 0

    if args.solo_faltantes and difieren:
        print("\n(--solo-faltantes: esas %d diferencias NO se tocan)" % len(difieren))
    elif cotejados >= 20 and len(difieren) > cotejados * 0.1:
        print("\n⚠ DEMASIADAS DIFERENCIAS: o el PDF cambio el orden de columnas, "
              "o los valores viejos estan mal. NO se carga nada. Mirar si "
              "alguna columna coincide SIEMPRE (esa esta bien mapeada) y usar "
              "--solo-faltantes para llenar huecos sin pisar nada.")
        return 2
    if not cotejados:
        print("\n⚠ No se pudo cotejar ni un valor contra la base: no hay meses "
              "en comun. Revisar a mano antes de cargar.")
        return 2

    if args.solo_leer:
        print("\n--solo-leer: no se escribio nada.")
        return 0

    a_cargar = filas
    if args.solo_faltantes:
        a_cargar = []
        for f in filas:
            b = base.get(f["FECHA"], {})
            nuevo = {"FECHA": f["FECHA"]}
            for col in COLUMNAS:
                if b.get(col) in (None, "") and f.get(col) is not None:
                    nuevo[col] = f[col]
            if len(nuevo) > 1:
                a_cargar.append(nuevo)
        print("--solo-faltantes: %d meses con algun hueco que llenar" % len(a_cargar))

    n = db.upsert_valores_ancha_bulk(SERIE, a_cargar, COLUMNAS, "FECHA")
    print("\n%s: +%d valores nuevos (el upsert no pisa lo ya cargado)" % (SERIE, n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
