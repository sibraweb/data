"""
Indices - API Server (Flask)

Mismo patrón que sibra-obra-repo/api/server.py: Flask + gspread (OAuth
desktop) + caché en memoria 90s + APScheduler para refrescar las fuentes
automáticas. Sirve también el frontend estático (index.html).

Fuentes, agrupadas por cadencia real (no por cómo las publica cada
organismo — varias de estas se "publican" a diario pero en el fondo
dependen de un único dato mensual, ver notas de cada grupo):

  DIARIO (mercado — cambian de verdad día a día):
    DOLAR, RIESGO_PAIS, MERVAL, BADLAR, TAMAR, BAIBAR, DEPOSITOS_30D,
    ADELANTOS_CTA_CTE, PRESTAMOS_PERSONALES, TIM

  MENSUAL, ~día 18 (derivan todas de un único dato mensual — IPC o RIPTE —
  aunque el BCRA las publique "a diario" por interpolación; pedirlas más
  seguido no trae información nueva, y el día 18 da margen a que INDEC ya
  haya publicado el IPC del mes, que suele salir ~14-15):
    CER, UVA, UVI, ICL, INFLACION_INDEC

  SEMANAL (se publican de forma irregular — hay que "pescarlas" sin
  castigar el sitio de origen con requests):
    RIPTE, REM, UOCRA, CAC

  MATERIALES       -> COTIZACIONES de sibra-obra-repo (Sheet ya existente),
                       filtrado por ID_PROVEEDOR — no se reingesta nada,
                       ese pipeline (mail -> parser -> Sheet) ya corre en Obra.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sheets
from ajuste import ajustar
from proyeccion import estimar_modelo, proyectar
from scrapers import argentinadatos, bcra, bcra_rem, camarco, dolares, investing, ripte, tim, uocra

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
app = Flask(__name__, static_folder=None)
CORS(app)

# ── Config de series propias (viven en SIBRATECH_INDICES) ──────────────────
SERIES = {
    "cer":  {"tab": "CER",  "fecha_col": "FECHA", "valor_col": "VALOR"},
    "uva":  {"tab": "UVA",  "fecha_col": "FECHA", "valor_col": "VALOR"},
    "uvi":  {"tab": "UVI",  "fecha_col": "FECHA", "valor_col": "VALOR"},
    "icl":  {"tab": "ICL",  "fecha_col": "FECHA", "valor_col": "VALOR"},
    "inflacion_indec": {"tab": "INFLACION_INDEC", "fecha_col": "FECHA", "valor_col": "VALOR"},
    "badlar": {"tab": "BADLAR", "fecha_col": "FECHA", "valor_col": "VALOR"},
    "tamar": {"tab": "TAMAR", "fecha_col": "FECHA", "valor_col": "VALOR"},
    "baibar": {"tab": "BAIBAR", "fecha_col": "FECHA", "valor_col": "VALOR"},
    "depositos_30d": {"tab": "DEPOSITOS_30D", "fecha_col": "FECHA", "valor_col": "VALOR"},
    "adelantos_cta_cte": {"tab": "ADELANTOS_CTA_CTE", "fecha_col": "FECHA", "valor_col": "VALOR"},
    "prestamos_personales": {"tab": "PRESTAMOS_PERSONALES", "fecha_col": "FECHA", "valor_col": "VALOR"},
    "tim": {"tab": "TIM", "fecha_col": "FECHA", "valor_col": "VALOR"},
    "riesgo_pais": {"tab": "RIESGO_PAIS", "fecha_col": "FECHA", "valor_col": "VALOR"},
    "merval": {"tab": "MERVAL", "fecha_col": "FECHA", "valor_col": "VALOR"},
    "ripte": {"tab": "RIPTE", "fecha_col": "FECHA", "valor_col": "RIPTE"},
    "uocra": {"tab": "UOCRA", "fecha_col": "FECHA", "valor_col": "OFICIAL"},
    "construccion": {"tab": "CONSTRUCCION", "fecha_col": "FECHA", "valor_col": "INDICE_GENERAL"},
    "cac": {"tab": "CAC", "fecha_col": "FECHA", "valor_col": "COSTO_CONSTRUCCION"},
}

# Series BCRA simples ("fecha"/"valor") que se vuelcan 1:1 a su propia hoja,
# agrupadas por cadencia real (ver docstring del módulo).
SERIES_BCRA_DIARIAS = [
    ("BADLAR", bcra.fetch_badlar), ("TAMAR", bcra.fetch_tamar), ("BAIBAR", bcra.fetch_baibar),
    ("DEPOSITOS_30D", bcra.fetch_depositos_30d), ("ADELANTOS_CTA_CTE", bcra.fetch_adelantos_cta_cte),
    ("PRESTAMOS_PERSONALES", bcra.fetch_prestamos_personales),
]
SERIES_BCRA_MENSUALES = [
    ("CER", bcra.fetch_cer), ("UVA", bcra.fetch_uva), ("UVI", bcra.fetch_uvi),
    ("ICL", bcra.fetch_icl), ("INFLACION_INDEC", bcra.fetch_inflacion_mensual),
]

# Familias para las que tiene sentido ofrecer una proyección (relación
# histórica con CER/dólar + curva de previsión del REM)
PROYECTABLES = {"uocra", "construccion", "ripte"}

DOLAR_TAB = "DOLAR"
DOLAR_COLUMNAS = {
    "dolar_oficial": "OFICIAL_VENTA",
    "dolar_blue": "BLUE_VENTA",
    "dolar_mep": "MEP_VENTA",
    "dolar_ccl": "CCL_VENTA",
    "dolar_mayorista": "MAYORISTA_VENTA",
}

# Proveedores de materiales ya cargados en Obra vía el pipeline de Gmail
# (ver sibra-obra-repo/api/PARSERS_LOG.md). Che Camba y Electropunto quedan
# pendientes hasta tener su parser configurado en Obra.
PROVEEDORES_MATERIALES = {
    "43": "Cerámica Norte",
    "12": "Construcciones en Seco",
    "64": "SERINAR",
    "229": "Electro Punto",  # confirmado en ENTIDADES: ID 229 = ELECTRO PUNTO SRL (razón social GAIPI SRL);
                             # ya tiene 3 vínculos cargados en MAESTRO_VINCULOS (cables, caño rígido)
}
# Che Camba = ID 51 en ENTIDADES (CHECAMBA MATERIALES SRL) — todavía sin
# cotizaciones/vínculos cargados, agregar acá cuando tenga datos.

REM_TABS = {"ipc": "REM_IPC", "fx": "REM_FX"}
REM_HEADERS = ["CLAVE", "FECHA_PRONOSTICO", "PERIODO", "MEDIANA", "PROMEDIO",
               "DESVIO", "MAXIMO", "MINIMO", "PERCENTIL_90"]


def _sheet_id():
    sid = sheets.INDICES_SHEET_ID or sheets.ensure_indices_sheet()
    return sid


# ── Series propias ──────────────────────────────────────────────────────────

@app.route("/api/series/<familia>")
def get_serie(familia):
    cfg = SERIES.get(familia)
    if not cfg:
        return jsonify({"error": f"familia desconocida: {familia}"}), 404
    records = sheets.read_records(_sheet_id(), cfg["tab"])
    return jsonify(records)


@app.route("/api/series/dolar")
def get_dolar():
    records = sheets.read_records(_sheet_id(), DOLAR_TAB)
    return jsonify(records)


# ── Materiales (leídos de Obra, no de nuestra Sheet) ────────────────────────

@app.route("/api/materiales/proveedores")
def get_proveedores():
    return jsonify(PROVEEDORES_MATERIALES)


@app.route("/api/materiales/<id_proveedor>")
def get_materiales(id_proveedor):
    if id_proveedor not in PROVEEDORES_MATERIALES:
        return jsonify({"error": "proveedor no reconocido o sin parser todavía"}), 404
    records = sheets.read_records(
        sheets.OBRA_PRECIOS_SHEET_ID, "COTIZACIONES",
        cache_key=f"obra_cotizaciones:{id_proveedor}",
    )
    filtradas = [r for r in records if str(r.get("ID_PROVEEDOR")) == id_proveedor]
    return jsonify(filtradas)


# ── REM (previsiones BCRA: IPC y tipo de cambio) ────────────────────────────

def _curva_rem_actual(tipo: str) -> tuple[str | None, list[dict]]:
    tab = REM_TABS.get(tipo)
    if not tab:
        return None, []
    records = sheets.read_records(_sheet_id(), tab)
    if not records:
        return None, []
    ultima_fecha = max(r["FECHA_PRONOSTICO"] for r in records)
    curva = sorted(
        (r for r in records if r["FECHA_PRONOSTICO"] == ultima_fecha),
        key=lambda r: r["PERIODO"],
    )
    return ultima_fecha, curva


@app.route("/api/rem/<tipo>")
def get_rem(tipo):
    if tipo not in REM_TABS:
        return jsonify({"error": f"tipo desconocido: {tipo} (usar 'ipc' o 'fx')"}), 404
    relevamiento, curva = _curva_rem_actual(tipo)
    return jsonify({"relevamiento": relevamiento, "curva": curva})


# ── Proyección (relación histórica con CER/dólar + curva REM) ──────────────

@app.route("/api/proyectar")
def get_proyeccion():
    familia = request.args.get("familia")
    if familia not in PROYECTABLES:
        return jsonify({
            "error": f"familia no proyectable: {familia} (usar: {', '.join(sorted(PROYECTABLES))})"
        }), 404

    sid = _sheet_id()
    cfg = SERIES[familia]
    objetivo = sheets.read_records(sid, cfg["tab"])
    cer = sheets.read_records(sid, "CER")
    dolar = sheets.read_records(sid, DOLAR_TAB)

    modelo = estimar_modelo(objetivo, cfg["fecha_col"], cfg["valor_col"], cer, dolar)
    if modelo is None:
        return jsonify({
            "error": "no hay suficiente historia en común (mínimo 6 meses) para estimar el modelo"
        }), 422

    _, curva_ipc = _curva_rem_actual("ipc")
    _, curva_fx = _curva_rem_actual("fx")
    curva_proyectada = proyectar(modelo, curva_ipc, curva_fx)

    return jsonify({"modelo": modelo, "proyeccion": curva_proyectada})


# ── Ajuste / comparación genérico ───────────────────────────────────────────

def _serie_indice(nombre_indice: str):
    """Devuelve (records, fecha_col, valor_col) para un nombre de índice elegible en el selector de ajuste."""
    if nombre_indice in ("cer", "uva"):
        cfg = SERIES[nombre_indice]
        return sheets.read_records(_sheet_id(), cfg["tab"]), cfg["fecha_col"], cfg["valor_col"]
    if nombre_indice in DOLAR_COLUMNAS:
        return sheets.read_records(_sheet_id(), DOLAR_TAB), "FECHA", DOLAR_COLUMNAS[nombre_indice]
    return None, None, None


@app.route("/api/ajustar")
def get_ajustado():
    familia = request.args.get("familia")
    indice = request.args.get("indice", "ninguno")

    if familia in SERIES:
        cfg = SERIES[familia]
        base = sheets.read_records(_sheet_id(), cfg["tab"])
        base_fecha, base_valor = cfg["fecha_col"], cfg["valor_col"]
    elif familia and familia.startswith("mat:"):
        id_prov = familia.split(":", 1)[1]
        base = [
            r for r in sheets.read_records(sheets.OBRA_PRECIOS_SHEET_ID, "COTIZACIONES",
                                            cache_key=f"obra_cotizaciones:{id_prov}")
            if str(r.get("ID_PROVEEDOR")) == id_prov
        ]
        base_fecha, base_valor = "FECHA", "PRECIO"
    else:
        return jsonify({"error": f"familia desconocida: {familia}"}), 404

    if indice == "ninguno":
        resultado = ajustar(base, None, base_fecha, base_valor, modo="nominal")
    else:
        idx_records, idx_fecha, idx_valor = _serie_indice(indice)
        if idx_records is None:
            return jsonify({"error": f"índice desconocido: {indice}"}), 404
        resultado = ajustar(base, idx_records, base_fecha, base_valor, idx_fecha, idx_valor, modo="ratio")

    return jsonify(resultado)


# ── Refresh manual + scheduler ──────────────────────────────────────────────

def _refrescar_series_bcra(lista):
    sid = _sheet_id()
    for tab, fetch_fn in lista:
        serie = fetch_fn()
        n = sheets.upsert_series(sid, tab, ["FECHA", "VALOR"], "FECHA",
                                  [{"FECHA": r["fecha"], "VALOR": r["valor"]} for r in serie])
        print(f"[scheduler] {tab} +{n} filas")


def refrescar_bcra_diarias():
    _refrescar_series_bcra(SERIES_BCRA_DIARIAS)


def refrescar_bcra_mensuales():
    _refrescar_series_bcra(SERIES_BCRA_MENSUALES)


def refrescar_tim():
    sid = _sheet_id()
    serie = tim.fetch_tim()
    n = sheets.upsert_series(sid, "TIM", ["FECHA", "VALOR"], "FECHA", serie)
    print(f"[scheduler] TIM +{n} filas")


def refrescar_riesgo_pais():
    sid = _sheet_id()
    serie = argentinadatos.fetch_riesgo_pais()
    n = sheets.upsert_series(sid, "RIESGO_PAIS", ["FECHA", "VALOR"], "FECHA", serie)
    print(f"[scheduler] RIESGO_PAIS +{n} filas")


def refrescar_merval():
    sid = _sheet_id()
    serie = investing.fetch_merval()
    n = sheets.upsert_series(sid, "MERVAL", ["FECHA", "VALOR"], "FECHA", serie)
    print(f"[scheduler] MERVAL +{n} filas")


def refrescar_cac():
    sid = _sheet_id()
    serie = camarco.fetch_cac()
    headers = ["FECHA", "COSTO_CONSTRUCCION", "MATERIALES", "MANO_DE_OBRA"]
    n = sheets.upsert_series(sid, "CAC", headers, "FECHA", serie)
    print(f"[scheduler] CAC +{n} filas (cifrasonline no siempre tiene el último mes)")


def refrescar_uocra():
    sid = _sheet_id()
    headers = [
        "FECHA", "OFICIAL_ESPECIALIZADO", "OFICIAL", "MEDIO_OFICIAL", "AYUDANTE", "SERENO",
        "OFICIAL_ESPECIALIZADO_NO_REM", "OFICIAL_NO_REM", "MEDIO_OFICIAL_NO_REM",
        "AYUDANTE_NO_REM", "SERENO_NO_REM",
    ]
    serie = uocra.fetch_uocra()
    n = sheets.upsert_series(sid, "UOCRA", headers, "FECHA", serie)
    print(f"[scheduler] UOCRA +{n} filas (algunos meses solo salen como PDF escaneado, sin OCR quedan para carga manual; "
          f"no remunerativo no siempre se puede leer por formato inconsistente del PDF fuente)")

    adic_headers = ["CLAVE", "CONCEPTO", "VALOR", "UNIDAD", "DESDE", "HASTA"]
    adicionales = uocra.fetch_adicionales_76_75()
    n2 = sheets.upsert_series(sid, "UOCRA_ADICIONALES", adic_headers, "CLAVE", adicionales)
    print(f"[scheduler] UOCRA_ADICIONALES +{n2} filas (aporte solidario + contribución empresarial, solo 76/75)")


def refrescar_dolar():
    sid = _sheet_id()
    fila = dolares.fetch_actual()
    headers = ["FECHA", "OFICIAL_COMPRA", "OFICIAL_VENTA", "BLUE_COMPRA", "BLUE_VENTA",
               "MEP_COMPRA", "MEP_VENTA", "CCL_COMPRA", "CCL_VENTA",
               "MAYORISTA_COMPRA", "MAYORISTA_VENTA", "CRIPTO_COMPRA", "CRIPTO_VENTA",
               "TARJETA_COMPRA", "TARJETA_VENTA"]
    n = sheets.upsert_series(sid, DOLAR_TAB, headers, "FECHA", [fila])
    print(f"[scheduler] DOLAR +{n} filas")


def refrescar_ripte():
    sid = _sheet_id()
    serie = ripte.fetch_serie()
    n = sheets.upsert_series(sid, "RIPTE", ["FECHA", "PERIODO", "RIPTE", "VARIACION_MENSUAL"], "FECHA", serie)
    print(f"[scheduler] RIPTE +{n} filas")


def refrescar_rem():
    sid = _sheet_id()
    datos = bcra_rem.fetch_rem()
    for tipo, tab in REM_TABS.items():
        filas = datos.get(tipo, [])
        for f in filas:
            f["CLAVE"] = f"{f['FECHA_PRONOSTICO']}|{f['PERIODO']}"
        n = sheets.upsert_series(sid, tab, REM_HEADERS, "CLAVE", filas)
        print(f"[scheduler] {tab} +{n} filas")


FUENTES_MANUALES = {
    "bcra_diarias": refrescar_bcra_diarias,
    "bcra_mensuales": refrescar_bcra_mensuales,
    "dolar": refrescar_dolar,
    "ripte": refrescar_ripte,
    "rem": refrescar_rem,
    "tim": refrescar_tim,
    "riesgo_pais": refrescar_riesgo_pais,
    "merval": refrescar_merval,
    "cac": refrescar_cac,
    "uocra": refrescar_uocra,
}


@app.route("/api/refrescar/<fuente>", methods=["POST"])
def refrescar_manual(fuente):
    fn = FUENTES_MANUALES.get(fuente)
    if not fn:
        return jsonify({"error": f"fuente desconocida: {fuente} (usar: {', '.join(FUENTES_MANUALES)})"}), 404
    fn()
    return jsonify({"status": "ok"})


def iniciar_scheduler():
    for nombre, fn in FUENTES_MANUALES.items():
        try:
            fn()
        except Exception as exc:
            print(f"[scheduler] primer refresh de {nombre} falló: {exc}")

    sched = BackgroundScheduler(timezone="America/Argentina/Buenos_Aires")

    # Diario — mercado, cambia de verdad día a día
    sched.add_job(refrescar_bcra_diarias, "interval", hours=6)
    sched.add_job(refrescar_dolar, "interval", hours=4)
    sched.add_job(refrescar_riesgo_pais, "cron", hour=9)
    sched.add_job(refrescar_merval, "cron", hour=20)  # después del cierre de rueda
    sched.add_job(refrescar_tim, "cron", hour=9, minute=15)

    # Mensual, ~día 18 — todas derivan de un único dato mensual (IPC/RIPTE);
    # pedirlas más seguido no trae información nueva.
    sched.add_job(refrescar_bcra_mensuales, "cron", day=18, hour=8)

    # Semanal — publicación irregular, no vale la pena scrapear más seguido
    sched.add_job(refrescar_ripte, "interval", days=7)
    sched.add_job(refrescar_rem, "interval", days=7)
    sched.add_job(refrescar_uocra, "interval", days=7)
    sched.add_job(refrescar_cac, "interval", days=7)

    sched.start()
    return sched


# ── Frontend estático ────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("FLASK_PORT", 8100))
    iniciar_scheduler()
    app.run(host="0.0.0.0", port=port, debug=False)
