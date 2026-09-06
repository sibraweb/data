# -*- coding: utf-8 -*-
"""Mete el historico de materiales de Indices dentro de `cotizaciones`, para
que quede UNA sola lista de precios y no haya mas ensamblado.

Juan, 2026-09-06: *«enganchamos una lista de precios viejos con una nueva que
sale del modulo de insumos de obra... capaz cargas todos en la base de supabase
y listo, resuelto»* / *«tomas de ahi todo y ya no se ensambla»*.

QUE PASABA
----------
La pestana Materiales de Indices pegaba dos fuentes:
  - el historico propio (`materiales_cotizaciones`, semilla del Excel de Juan)
  - la lista viva, leida de la Sheet COTIZACIONES del Drive de Obra

y el enganche estaba ROTO hacia rato, sin que se notara:

  1. Obra migro COTIZACIONES a Postgres y dejo de usar la Sheet (su
     `_hoja_rows()` lee la tabla). Indices seguia leyendo la planilla, o sea
     una fuente que ya no alimenta nadie.
  2. Cada lado numeraba los proveedores distinto. Indices pedia el 43
     (Ceramica Norte); los datos usan el de Obra, el 23. Filtrando por 43 no
     volvia NADA de ninguna de las dos fuentes.

El sintoma era mudo: la pantalla igual mostraba los tres items curados —estan
escritos a mano en MATERIALES_CURADOS— pero con cero cotizaciones abajo.

QUE HACE ESTE SCRIPT
--------------------
Copia las 117 filas del historico a `cotizaciones` con `origen='HISTORICO'`.
No pisa nada: el historico va de 11-2018 a 03-2026 y lo que Obra tiene de
Ceramica Norte es del 29-06-2026 — se continuan, no se solapan.

Es IDEMPOTENTE: las filas van con id `HIST-#####` y se saltean las que ya
estan. Correrlo dos veces no duplica.

`materiales_cotizaciones` NO se borra. Queda como estaba, de respaldo: si algo
sale mal, el original sigue ahi para volver a mirarlo.

    py unificar_materiales_en_cotizaciones.py            # muestra que haria
    py unificar_materiales_en_cotizaciones.py --aplicar  # escribe
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import psycopg
from psycopg.rows import dict_row

# El historico es todo de Ceramica Norte. El id que vale es el de Obra, que es
# el que usa la lista viva — ver el punto 2 del docstring.
ID_PROVEEDOR = "23"
NOMBRE_PROVEEDOR = "Cerámica Norte SA"
ORIGEN = "HISTORICO"


def main() -> int:
    aplicar = "--aplicar" in sys.argv
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        print("falta SUPABASE_DB_URL en indices/.env")
        return 2

    hoy = dt.date.today().isoformat()
    with psycopg.connect(url, row_factory=dict_row) as cx:
        historico = cx.execute(
            "SELECT id_proveedor, descripcion, fecha, precio "
            "FROM materiales_cotizaciones ORDER BY descripcion, fecha"
        ).fetchall()
        ya_estan = {
            r["id"] for r in cx.execute(
                "SELECT id FROM cotizaciones WHERE id LIKE 'HIST-%'").fetchall()
        }

        filas, salteadas = [], 0
        for i, r in enumerate(historico, start=1):
            clave = "HIST-%05d" % i
            if clave in ya_estan:
                salteadas += 1
                continue
            filas.append((
                clave, "", r["descripcion"] or "", "",
                str(r["fecha"]), "" if r["precio"] is None else str(r["precio"]),
                "ARS", "", "",
                ID_PROVEEDOR, NOMBRE_PROVEEDOR, "", "", "", "", "",
                "historico de Indices (Excel de Juan), unificado el %s" % hoy,
                ORIGEN, "", "", "", "unificar_materiales", hoy, "",
            ))

        print("historico: %d filas · a insertar: %d · ya estaban: %d"
              % (len(historico), len(filas), salteadas))
        if filas:
            print("ejemplo:", filas[0][:6])
        if not filas:
            print("nada que hacer.")
            return 0
        if not aplicar:
            print("\n(simulacion — volver a correr con --aplicar para escribir)")
            return 0

        cols = ("id, cod_insumo, descripcion, unidad, fecha, precio, moneda, "
                "precio_ars_eq, tipo_cambio, id_proveedor, proveedor, "
                "cuit_proveedor, condicion_pago, incluye_flete, lugar_entrega, "
                "cantidad_min, notas, origen, id_ref, id_obra_ref, "
                "nombre_obra_ref, usuario, fecha_carga, cod_prov")
        marcas = ",".join(["%s"] * 24)
        with cx.cursor() as cur:
            cur.executemany(
                f"INSERT INTO cotizaciones ({cols}) VALUES ({marcas})", filas)
        cx.commit()
        total = cx.execute("SELECT count(*) AS n FROM cotizaciones").fetchone()["n"]
        print("insertadas %d · cotizaciones ahora tiene %d filas" % (len(filas), total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
