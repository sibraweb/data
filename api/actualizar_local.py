"""
Arranque rápido, sin Sheets ni OAuth: trae las series públicas (BCRA,
dólares, RIPTE, REM) y las deja en SIBRA-DATA-CORREGIDO/AUTO/, listas
para abrir en Excel. No toca los archivos originales de RAW/.

Uso:
    cd api
    python actualizar_local.py            # todo
    python actualizar_local.py bcra       # solo CER/UVA
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from export_data import exportar_tab
from scrapers import argentinadatos, bcra, bcra_rem, camarco, dolares, investing, ripte, tim, uocra

# (tab, función fetch_*) — todas devuelven [{"fecha", "valor"}, ...]
SERIES_BCRA = [
    ("CER", bcra.fetch_cer),
    ("UVA", bcra.fetch_uva),
    ("UVI", bcra.fetch_uvi),
    ("ICL", bcra.fetch_icl),
    ("BADLAR", bcra.fetch_badlar),
    ("INFLACION_INDEC", bcra.fetch_inflacion_mensual),
    ("BAIBAR", bcra.fetch_baibar),
    ("DEPOSITOS_30D", bcra.fetch_depositos_30d),
    ("ADELANTOS_CTA_CTE", bcra.fetch_adelantos_cta_cte),
    ("PRESTAMOS_PERSONALES", bcra.fetch_prestamos_personales),
    ("TAMAR", bcra.fetch_tamar),
]


def actualizar_bcra():
    for tab, fetch_fn in SERIES_BCRA:
        serie = fetch_fn()
        p = exportar_tab(tab, [{"FECHA": r["fecha"], "VALOR": r["valor"]} for r in serie])
        print(f"{tab:22s} -> {len(serie)} filas -> {p}")


def actualizar_tim():
    serie = tim.fetch_tim()
    p = exportar_tab("TIM", serie)
    print(f"TIM -> {len(serie)} filas -> {p}")


def actualizar_riesgo_pais():
    serie = argentinadatos.fetch_riesgo_pais()
    p = exportar_tab("RIESGO_PAIS", serie)
    print(f"RIESGO_PAIS -> {len(serie)} filas -> {p}")


def actualizar_merval():
    serie = investing.fetch_merval()
    p = exportar_tab("MERVAL", serie)
    print(f"MERVAL -> {len(serie)} filas -> {p}")


def actualizar_cac():
    serie = camarco.fetch_cac()
    p = exportar_tab("CAC", serie)
    print(f"CAC -> {len(serie)} filas (hasta {serie[-1]['FECHA'] if serie else '-'}, "
          f"cifrasonline no tiene lo más reciente) -> {p}")


def actualizar_dolar():
    fila = dolares.fetch_actual()
    p = exportar_tab("DOLAR", [fila])
    print(f"DOLAR -> 1 fila (hoy) -> {p}")


def actualizar_ripte():
    serie = ripte.fetch_serie()
    p = exportar_tab("RIPTE", serie)
    print(f"RIPTE -> {len(serie)} filas -> {p}")


def actualizar_uocra():
    serie = uocra.fetch_uocra()
    p = exportar_tab("UOCRA", serie)
    print(f"UOCRA -> {len(serie)} filas (algunos meses quedan afuera si el PDF "
          f"de ese acuerdo es una imagen escaneada, no hay OCR instalado) -> {p}")

    adicionales = uocra.fetch_adicionales_76_75()
    p2 = exportar_tab("UOCRA_ADICIONALES", adicionales)
    print(f"UOCRA_ADICIONALES -> {len(adicionales)} filas (aporte solidario + contribución "
          f"empresarial, solo convenio 76/75 — el seguro de vida se calcula, no se scrapea) -> {p2}")


def actualizar_rem():
    datos = bcra_rem.fetch_rem()
    for tipo, tab in (("ipc", "REM_IPC"), ("fx", "REM_FX"), ("ipc_interanual", "REM_IPC_INTERANUAL")):
        filas = datos.get(tipo, [])
        p = exportar_tab(tab, filas)
        print(f"{tab} -> {len(filas)} filas -> {p}")


ACCIONES = {
    "bcra": actualizar_bcra,
    "dolar": actualizar_dolar,
    "ripte": actualizar_ripte,
    "uocra": actualizar_uocra,
    "rem": actualizar_rem,
    "tim": actualizar_tim,
    "riesgo_pais": actualizar_riesgo_pais,
    "merval": actualizar_merval,
    "cac": actualizar_cac,
}


if __name__ == "__main__":
    objetivo = sys.argv[1] if len(sys.argv) > 1 else None
    if objetivo:
        ACCIONES[objetivo]()
    else:
        for nombre, fn in ACCIONES.items():
            print(f"=== {nombre} ===")
            try:
                fn()
            except Exception as exc:
                print(f"  ERROR: {exc}")
