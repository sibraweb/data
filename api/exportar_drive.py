# -*- coding: utf-8 -*-
"""Deja en Drive, como CSV, todo lo de CAMARCO y de INDEC para redeterminacion.

    py api/exportar_drive.py            # todo
    py api/exportar_drive.py --solo cac
    py api/exportar_drive.py --destino "C:\\tmp"

⚠ POR QUE CSV EN DRIVE Y NO SUPABASE. Juan, 13/09/2026: *«por ahora vamos a
poner todo esto de camarco y de indec en csv de drive; luego veremos que usamos
para supabase, en este caso no necesitamos la velocidad de calculo, necesitamos
tener disponible nomas y un manual de como usarlos»*. Va con la convencion de
la casa (bases/datos a H:\\My Drive\\web_sibra) y con la regla de que Supabase
no es para historicos.

⚠ LO QUE YA VIVE EN SUPABASE NO SE MUEVE. `series_valores`, `series_provisorios`
e `indec_op_*` siguen donde estan porque los consume el endpoint de
redeterminacion, que si necesita contestar rapido. Esto es una COPIA para tener
el dato a mano y poder abrirlo en una planilla; la fuente de verdad sigue siendo
la base. Si alguna vez divergen, manda la base.

⚠ SE REESCRIBE EL ARCHIVO ENTERO, no se agrega al final. Un CSV que se appendea
termina con el mismo periodo tres veces y nadie sabe cual vale.
"""
from __future__ import annotations

import argparse
import csv
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

import db  # noqa: E402

DESTINO = Path(r"H:\My Drive\web_sibra\indices")


def _escribir(destino: Path, nombre: str, columnas: list[str],
              filas: list[dict]) -> Path:
    """Un CSV con BOM, para que Excel en castellano lo abra bien.

    ⚠ utf-8-sig y no utf-8: sin el BOM, Excel lee los acentos como mojibake y
    el archivo "esta mal" para quien lo abre, aunque el dato este perfecto.
    """
    destino.mkdir(parents=True, exist_ok=True)
    ruta = destino / nombre
    with open(ruta, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columnas, extrasaction="ignore",
                           delimiter=";")
        w.writeheader()
        w.writerows(filas)
    print("   %-42s %6d filas" % (nombre, len(filas)))
    return ruta


# ── CAMARCO ─────────────────────────────────────────────────────────────────

def exportar_cargas(destino: Path) -> None:
    """El coeficiente sobre el jornal, item por item. Esto es el 2,15."""
    import camarco_cargas
    pubs = camarco_cargas.fetch_cargas_sociales()

    detalle, resumen = [], []
    for p in pubs:
        # control de suma, guardado EN EL CSV: si un dia el PDF cambia de
        # formato y se pierde un item, el archivo lo dice en vez de callarse
        sumandos = [i for i in p["ITEMS"] if i["CLASE"] == "sumando"]
        sub = next((i for i in p["ITEMS"] if i["CLASE"] == "subtotal"), None)
        cierra = ""
        if sub:
            antes = sum(i["INCIDENCIA"] for i in sumandos if i["LETRA"] < sub["LETRA"])
            despues = sum(i["INCIDENCIA"] for i in sumandos if i["LETRA"] > sub["LETRA"])
            ok_sub = abs(antes - sub["INCIDENCIA"]) <= 0.02
            ok_tot = abs(sub["INCIDENCIA"] + despues - p["COEFICIENTE"]) <= 0.02
            cierra = "SI" if (ok_sub and ok_tot) else "NO"
        resumen.append({
            "grupo": p["GRUPO"], "vigencia": p["VIGENCIA"],
            "publicado": p["PUBLICADO"], "coeficiente_pct": p["COEFICIENTE"],
            "factor": round(p["COEFICIENTE"] / 100.0, 6),
            "art_cuota_pactada_pct": p["ART_CUOTA_PACTADA"],
            "art_cuota_mes": p["ART_CUOTA_MES"],
            "suma_controlada": cierra, "fuente": p["FUENTE"],
        })
        for i in p["ITEMS"]:
            detalle.append({
                "grupo": p["GRUPO"], "vigencia": p["VIGENCIA"],
                "publicado": p["PUBLICADO"], "item": i["LETRA"],
                "concepto": i["CONCEPTO"], "incidencia_pct": i["INCIDENCIA"],
                "clase": i["CLASE"], "fuente": p["FUENTE"],
            })

    _escribir(destino, "camarco_cargas_sociales_coeficiente.csv",
              ["grupo", "vigencia", "publicado", "coeficiente_pct", "factor",
               "art_cuota_pactada_pct", "art_cuota_mes", "suma_controlada",
               "fuente"], resumen)
    _escribir(destino, "camarco_cargas_sociales_items.csv",
              ["grupo", "vigencia", "publicado", "item", "concepto",
               "incidencia_pct", "clase", "fuente"], detalle)


def exportar_cac(destino: Path) -> None:
    """El indicador CAC con la marca de provisorio de CAMARCO."""
    valores = db.leer_serie_ancha("CAC")
    flags = {}
    try:
        with db._conectar() as cx, cx.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (fecha) fecha, provisorio, foto
                  FROM series_provisorios WHERE serie = 'CAC'
                 ORDER BY fecha, foto DESC""")
            flags = {r["fecha"].isoformat(): r for r in cur.fetchall()}
    except Exception as e:
        print("   (sin flags de provisorio: %s)" % e)

    filas = []
    for v in valores:
        f = v.get("FECHA")
        fl = flags.get(f)
        filas.append({
            "fecha": f,
            "costo_construccion": v.get("COSTO_CONSTRUCCION"),
            "materiales": v.get("MATERIALES"),
            "mano_de_obra": v.get("MANO_DE_OBRA"),
            # ⚠ VACIO NO ES "DEFINITIVO": es que no lo sabemos para ese mes
            "provisorio": ("" if fl is None
                           else ("SI" if fl["provisorio"] else "NO")),
            "flag_leido_el": fl["foto"].isoformat() if fl else "",
        })
    _escribir(destino, "camarco_cac.csv",
              ["fecha", "costo_construccion", "materiales", "mano_de_obra",
               "provisorio", "flag_leido_el"], filas)


def exportar_acuerdos(destino: Path, con_pdf: int = 12) -> None:
    """Los acuerdos salariales con su fecha de publicacion y de firma."""
    import camarco_laboral
    acs = camarco_laboral.fetch_acuerdos(paginas=4, con_pdf=con_pdf)
    filas = [{
        "fecha_publicacion": a["FECHA_PUBLICACION"],
        "fecha_suscripcion": a["FECHA_SUSCRIPCION"] or "",
        "tipo": a["TIPO"],
        "convenios": ",".join(a["CONVENIOS"]),
        "periodos_que_rige": ",".join(a["PERIODOS"]),
        "titulo": a["TITULO"],
        "link": a["LINK"],
        "pdfs": " | ".join(a["PDFS"]),
    } for a in acs]
    _escribir(destino, "camarco_acuerdos_salariales.csv",
              ["fecha_publicacion", "fecha_suscripcion", "tipo", "convenios",
               "periodos_que_rige", "titulo", "link", "pdfs"], filas)


def exportar_uocra(destino: Path) -> None:
    """Los jornales UOCRA y los conceptos adicionales (aportes, seguro)."""
    filas = []
    for v in db.leer_serie_ancha("UOCRA"):
        fila = {"fecha": v.get("FECHA")}
        for k, x in v.items():
            if k != "FECHA":
                fila[k.lower()] = x
        filas.append(fila)
    cols = ["fecha"] + sorted({k for f in filas for k in f if k != "fecha"})
    _escribir(destino, "uocra_jornales.csv", cols, filas)

    ad = [{
        "concepto_num": a.get("CONCEPTO_NUM"), "titulo": a.get("TITULO"),
        "valor": a.get("VALOR"), "unidad": a.get("UNIDAD"),
        "desde": a.get("DESDE"), "hasta": a.get("HASTA"),
        "acuerdo_ref": a.get("ACUERDO_REF"), "texto": a.get("TEXTO"),
    } for a in db.leer_uocra_adicionales()]
    _escribir(destino, "uocra_adicionales.csv",
              ["concepto_num", "titulo", "valor", "unidad", "desde", "hasta",
               "acuerdo_ref", "texto"], ad)


# ── INDEC ───────────────────────────────────────────────────────────────────

def exportar_indec(destino: Path) -> None:
    """Los 436 indices por insumo, sus valores y el historial de revisiones."""
    consultas = [
        ("indec_op_conceptos.csv",
         ["grupo", "codigo", "origen", "cuadro", "descripcion", "publicacion",
          "clasificacion", "nivel"],
         "SELECT grupo, codigo, origen, cuadro, descripcion, publicacion, "
         "clasificacion, nivel FROM indec_op_conceptos "
         "ORDER BY grupo, codigo, origen, cuadro"),
        ("indec_op_valores.csv",
         ["grupo", "codigo", "origen", "cuadro", "periodo", "indice", "provisorio"],
         "SELECT grupo, codigo, origen, cuadro, periodo, indice, provisorio "
         "FROM indec_op_valores ORDER BY periodo, grupo, codigo"),
        ("indec_op_revisiones.csv",
         ["grupo", "codigo", "origen", "cuadro", "periodo", "foto", "indice",
          "provisorio"],
         "SELECT grupo, codigo, origen, cuadro, periodo, foto, indice, provisorio "
         "FROM indec_op_revisiones ORDER BY periodo, foto, grupo, codigo"),
    ]
    for nombre, cols, sql in consultas:
        with db._conectar() as cx, cx.cursor() as cur:
            cur.execute(sql)
            filas = [{c: (v.isoformat() if hasattr(v, "isoformat") else v)
                      for c, v in r.items()} for r in cur.fetchall()]
        _escribir(destino, nombre, cols, filas)


TAREAS = {
    "cargas": exportar_cargas,
    "cac": exportar_cac,
    "acuerdos": exportar_acuerdos,
    "uocra": exportar_uocra,
    "indec": exportar_indec,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--destino", default=str(DESTINO))
    ap.add_argument("--solo", choices=sorted(TAREAS), action="append")
    args = ap.parse_args()

    destino = Path(args.destino)
    cuales = args.solo or sorted(TAREAS)
    print("destino: %s" % destino)
    for nombre in cuales:
        print("\n== %s ==" % nombre)
        try:
            TAREAS[nombre](destino)
        except Exception as e:
            # ⚠ una tarea que falla NO frena las otras: si CAMARCO no contesta,
            # los CSV de INDEC igual se escriben y el aviso queda a la vista.
            print("   FALLO: %s: %s" % (type(e).__name__, e))
    print("\nlisto. El manual de como usarlos: MANUAL_REDETERMINACION_Y_MANO_DE_OBRA.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
