# -*- coding: utf-8 -*-
"""El histórico de TODOS los dólares, no solo de tres.

Juan, 2026-09-09: *«en índices no tenemos base de dólar MEP parece, porque
quise correr por MEP unos valores y no hizo nada; no sé si el oficial también
tenemos así, y no sé si estamos relevando blue también»*.

Lo medido en la base ese día:

    OFICIAL / BLUE / MAYORISTA   3.946 días   2011-01-03 -> hoy    ✓
    MEP / CCL / CRIPTO / TARJETA    14 días   2026-07-14 -> hoy    ⚠

O sea: blue y oficial están completos, y **MEP tiene dos meses**. Por eso una
cuenta hecha «por MEP» hacia atrás no devolvía nada — no es que no exista la
serie, es que no hay con qué.

POR QUÉ FALTABAN, QUE NO ERA LA FUENTE
--------------------------------------
`scrapers/dolares.py` lee dolarapi.com, que **solo da el valor de hoy**: el
histórico se arma día a día desde que el scheduler arrancó, y el scheduler
arrancó el 14 de julio. Las otras tres tienen historia porque alguien las
backfilleó una vez.

Y ese backfill —`api/backfill_dolar.py`— tenía el bug: sus `DOLAR_HEADERS`
declaran las catorce columnas, MEP y CCL incluidas, pero su mapa
`CASA_A_COLUMNAS` solo traduce tres:

    "oficial", "blue", "mayorista"

Las otras cuatro nunca se pedían. La lista de arriba prometía algo que la de
abajo no cumplía, y como el script terminaba bien, nadie lo notó. (Además
escribe en Google Sheets, que es el camino viejo: los datos hoy viven en
Supabase.)

LA FUENTE
---------
`api.argentinadatos.com/v1/cotizaciones/dolares/<casa>`, del mismo autor que
dolarapi, con la serie diaria completa. Verificado el 2026-09-09:

    oficial          5.729 días   desde 2011-01-03
    blue             5.729        desde 2011-01-03
    mayorista        5.729        desde 2011-01-03
    contadoconliqui  4.999        desde 2013-01-02
    bolsa (MEP)      2.873        desde 2018-10-29
    tarjeta          2.453        desde 2019-12-23
    cripto           1.311        desde 2023-02-07

⚠ MEP NO EMPIEZA EN 2011 Y NO ES UN DEFECTO: el dólar bolsa como referencia
diaria no existía antes. Una cuenta «a MEP» de 2015 no tiene respuesta, y es
mejor que la serie diga que no llega a que alguien la complete con el oficial.

⚠ NO PISA NADA. El `ON CONFLICT DO NOTHING` de `upsert_valores_ancha_bulk`
protege lo que ya está: si un día nuestro scraper y esta API discrepan, gana
el que ya estaba guardado. Correrlo dos veces es inofensivo.

Uso
---
    py cargar_dolar_historico.py            # dice qué traería
    py cargar_dolar_historico.py --aplicar
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent

# ⚠ El .env ANTES de importar db: `db.py` lee os.environ al conectar y no
# carga el archivo solo. Sin esto se estrella con «Falta SUPABASE_DB_URL»
# teniéndolo al lado.
try:
    from dotenv import load_dotenv
    load_dotenv(BASE.parent / ".env")
except Exception:
    pass

sys.path.insert(0, str(BASE.parent))
sys.path.insert(0, str(BASE))

import requests                                            # noqa: E402
import db                                                  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

API = "https://api.argentinadatos.com/v1/cotizaciones/dolares"

# la casa que usa la API -> nuestro prefijo de columna en la serie DOLAR
CASAS = {
    "oficial": "OFICIAL",
    "blue": "BLUE",
    "mayorista": "MAYORISTA",
    "bolsa": "MEP",
    "contadoconliqui": "CCL",
    "cripto": "CRIPTO",
    "tarjeta": "TARJETA",
}

HEADERS = [f"{p}_{q}" for p in CASAS.values() for q in ("COMPRA", "VENTA")]


def bajar(casa: str) -> list[dict]:
    r = requests.get(f"{API}/{casa}", timeout=60)
    r.raise_for_status()
    return r.json()


def armar() -> tuple[list[dict], dict]:
    """Una fila por fecha con las 14 columnas que haya."""
    por_fecha: dict[str, dict] = {}
    resumen = {}
    for casa, pref in CASAS.items():
        try:
            filas = bajar(casa)
        except Exception as e:
            print("   ⚠ %-16s no se pudo bajar: %s" % (casa, str(e)[:70]))
            resumen[pref] = (0, None, None)
            continue
        for f in filas:
            fecha = (f.get("fecha") or "")[:10]
            if not fecha:
                continue
            fila = por_fecha.setdefault(fecha, {"FECHA": fecha})
            if f.get("compra") is not None:
                fila[f"{pref}_COMPRA"] = f["compra"]
            if f.get("venta") is not None:
                fila[f"{pref}_VENTA"] = f["venta"]
        resumen[pref] = (len(filas),
                         filas[0]["fecha"][:10] if filas else None,
                         filas[-1]["fecha"][:10] if filas else None)
        print("   %-10s %5d días   %s -> %s" % ((pref,) + resumen[pref][1:] if False
                                                else (pref, resumen[pref][0],
                                                      resumen[pref][1], resumen[pref][2])))
    return [por_fecha[k] for k in sorted(por_fecha)], resumen


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args()

    print("Bajando el histórico de %d casas de cambio…\n" % len(CASAS))
    filas, _ = armar()
    print("\n%d fecha(s) distintas, de %s a %s"
          % (len(filas), filas[0]["FECHA"] if filas else "?",
             filas[-1]["FECHA"] if filas else "?"))

    print("\nLo que YA hay en la base:")
    try:
        actual = db.leer_serie_ancha("DOLAR")            # si existe el helper
    except Exception:
        actual = None
    if actual is None:
        import psycopg
        import os
        with psycopg.connect(os.environ["SUPABASE_DB_URL"]) as cx:
            with cx.cursor() as cur:
                cur.execute("""select columna, count(*), min(fecha), max(fecha)
                                 from series_valores where serie='DOLAR'
                                group by 1 order by 1""")
                for col, n, d, h in cur.fetchall():
                    print("   %-18s %5d  %s -> %s" % (col, n, d, h))

    if not a.aplicar:
        print("\nSIMULACIÓN — con --aplicar se escribe. No pisa lo que ya está.")
        return 0

    n = db.upsert_valores_ancha_bulk("DOLAR", filas, HEADERS)
    print("\n✓ %d valor(es) nuevos" % n)

    import psycopg
    import os
    with psycopg.connect(os.environ["SUPABASE_DB_URL"]) as cx:
        with cx.cursor() as cur:
            cur.execute("""select columna, count(*), min(fecha), max(fecha)
                             from series_valores where serie='DOLAR'
                            group by 1 order by 1""")
            print("\nCómo quedó:")
            for col, cn, d, h in cur.fetchall():
                print("   %-18s %5d  %s -> %s" % (col, cn, d, h))
    return 0


if __name__ == "__main__":
    sys.exit(main())
