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
from rem_estimaciones import construir_curva_mensual, resumen_por_anio
from resumen import resumen_serie
from resumen import variacion as calcular_variacion
from scrapers import alquileres, argentinadatos, bcra, bcra_rem, camarco, dolares, icc, investing, ripte, salarios, tim, uocra

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
    "salarios": {"tab": "SALARIOS", "fecha_col": "FECHA", "valor_col": "INDICE_TOTAL"},
    "icc_caba": {"tab": "ICC_CABA", "fecha_col": "FECHA", "valor_col": "GENERAL"},
    "icc_buenos_aires": {"tab": "ICC_BUENOS_AIRES", "fecha_col": "FECHA", "valor_col": "GENERAL"},
    "icc_cordoba": {"tab": "ICC_CORDOBA", "fecha_col": "FECHA", "valor_col": "GENERAL"},
    "icc_santa_fe": {"tab": "ICC_SANTA_FE", "fecha_col": "FECHA", "valor_col": "GENERAL"},
    "alquiler_caba": {"tab": "ALQUILER_CABA", "fecha_col": "FECHA", "valor_col": "PROMEDIO"},
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

# Familias con más de una columna elegible dentro de la misma hoja (ej.
# "construccion:MATERIALES" o "cac:MANO_DE_OBRA") — se suman a SERIES, que
# solo permite una columna fija por familia.
SERIES_MULTI_COLUMNA = {
    "construccion": {"tab": "CONSTRUCCION", "fecha_col": "FECHA",
                      "columnas": ["INDICE_GENERAL", "MATERIALES", "MANO_DE_OBRA", "PROVISIONES"]},
    "cac": {"tab": "CAC", "fecha_col": "FECHA",
            "columnas": ["COSTO_CONSTRUCCION", "MATERIALES", "MANO_DE_OBRA"]},
    # "uocra:OFICIAL", "uocra:SERENO", etc. — para la calculadora de mano de
    # obra / redeterminación, que necesita el básico de CUALQUIER categoría
    # (no solo "Oficial", que es la única que vive en SERIES).
    "uocra": {"tab": "UOCRA", "fecha_col": "FECHA",
              "columnas": ["OFICIAL_ESPECIALIZADO", "OFICIAL", "MEDIO_OFICIAL", "AYUDANTE", "SERENO"]},
    "salarios": {"tab": "SALARIOS", "fecha_col": "FECHA",
                 "columnas": ["PRIVADO_REGISTRADO", "PUBLICO", "TOTAL_REGISTRADO", "NO_REGISTRADO", "INDICE_TOTAL"]},
    "icc_caba": {"tab": "ICC_CABA", "fecha_col": "FECHA",
                 "columnas": ["GENERAL", "MATERIALES", "MANO_DE_OBRA", "GASTOS"]},
    "icc_buenos_aires": {"tab": "ICC_BUENOS_AIRES", "fecha_col": "FECHA",
                          "columnas": ["GENERAL", "MATERIALES", "MANO_DE_OBRA", "GASTOS"]},
    "icc_cordoba": {"tab": "ICC_CORDOBA", "fecha_col": "FECHA",
                    "columnas": ["GENERAL", "MATERIALES", "MANO_DE_OBRA", "GASTOS"]},
    "icc_santa_fe": {"tab": "ICC_SANTA_FE", "fecha_col": "FECHA",
                     "columnas": ["GENERAL", "MATERIALES", "MANO_DE_OBRA", "GASTOS"]},
    "alquiler_caba": {"tab": "ALQUILER_CABA", "fecha_col": "FECHA",
                      "columnas": ["PROMEDIO", "PRECIO_2_AMBIENTES", "PRECIO_3_AMBIENTES"]},
}

# Series que aparecen en la tabla Resumen (nombre visible -> familia resoluble
# por _resolver_familia). Réplica de la hoja "Resumen Indices" del Excel.
RESUMEN_SERIES = [
    ("UOCRA Oficial", "uocra"),
    ("RIPTE", "ripte"),
    ("Dólar oficial", "dolar:dolar_oficial"),
    ("Dólar blue", "dolar:dolar_blue"),
    ("Dólar MEP", "dolar:dolar_mep"),
    ("CER", "cer"),
    ("UVA", "uva"),
    ("UVI", "uvi"),
    ("ICL (alquileres)", "icl"),
    ("CAMARCO costo construcción", "cac:COSTO_CONSTRUCCION"),
    ("CAMARCO materiales", "cac:MATERIALES"),
    ("CAMARCO mano de obra", "cac:MANO_DE_OBRA"),
    ("Construcción general (APYMECO)", "construccion:INDICE_GENERAL"),
    ("Índice de Salarios INDEC", "salarios:INDICE_TOTAL"),
    ("ICC Buenos Aires (costo construcción)", "icc_buenos_aires:GENERAL"),
    ("Alquiler CABA (promedio, fuente 2013-2019)", "alquiler_caba:PROMEDIO"),
    ("Riesgo país", "riesgo_pais"),
    ("MERVAL", "merval"),
]

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
# Interanual a CUALQUIER mes objetivo (dic = año calendario completo; otros
# meses = 12/24 meses hacia adelante desde la encuesta) — ver scrapers/bcra_rem.py
REM_INTERANUAL_TAB = "REM_IPC_INTERANUAL"
REM_INTERANUAL_HEADERS = ["CLAVE", "FECHA_PRONOSTICO", "PERIODO", "MEDIANA", "PROMEDIO",
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

# Materiales curados por proveedor: si un proveedor aparece acá, el selector
# de la ventana Materiales SOLO ofrece estos ítems (no "todos los que
# cotizó alguna vez", que mezclaba productos sin relación) — el resto de los
# proveedores sin curar todavía muestran todos los ítems descubiertos, como
# antes. Se completa a pedido de Juan a medida que define qué necesita de
# cada proveedor.
MATERIALES_CURADOS = {
    "43": [  # Cerámica Norte
        "CEMENTO PORTLAND X 25 KG. (LOMA NEGRA)-25",
        "HIERRO Aº TORS.Ø 10-BR X 12MT.",
        "LADRILLO HUECO DE 1º 18X18X25-5",
    ],
    # "64": [...]  # SERINAR — caño Awaduct 110mm x 4mts pedido por Juan,
    #                todavía no aparece en ninguna cotización cargada (solo
    #                hay accesorios de 50/63mm) — pendiente hasta que llegue
    #                un mail con ese ítem.
}


def _cotizaciones_material(id_proveedor: str, descripcion: str | None = None) -> list[dict]:
    """Cotizaciones en vivo de Obra (pipeline de mail, vía COTIZACIONES)
    SUPERPUESTAS con el histórico propio cargado a mano en
    MATERIALES_HISTORICO (seed del Excel de Juan) — una sola serie por
    (proveedor, material), el histórico rellena lo viejo y COTIZACIONES
    sigue sumando lo nuevo sin que haya que volver a tocar el histórico."""
    vivo = [
        r for r in sheets.read_records(sheets.OBRA_PRECIOS_SHEET_ID, "COTIZACIONES",
                                        cache_key=f"obra_cotizaciones:{id_proveedor}")
        if str(r.get("ID_PROVEEDOR")) == id_proveedor
    ]
    historico = [
        r for r in sheets.read_records(_sheet_id(), "MATERIALES_HISTORICO")
        if str(r.get("ID_PROVEEDOR")) == id_proveedor
    ]
    combinado = historico + vivo
    if descripcion:
        combinado = [r for r in combinado if r.get("DESCRIPCION") == descripcion]
    return combinado


@app.route("/api/materiales/proveedores")
def get_proveedores():
    return jsonify(PROVEEDORES_MATERIALES)


@app.route("/api/materiales/<id_proveedor>")
def get_materiales(id_proveedor):
    if id_proveedor not in PROVEEDORES_MATERIALES:
        return jsonify({"error": "proveedor no reconocido o sin parser todavía"}), 404
    return jsonify(_cotizaciones_material(id_proveedor))


@app.route("/api/materiales/<id_proveedor>/items")
def get_materiales_items(id_proveedor):
    """Lista de materiales elegibles para ese proveedor. Si está curado
    (MATERIALES_CURADOS), son exactamente esos — si no, se descubren todos
    los que tengan al menos una cotización (comportamiento previo)."""
    if id_proveedor not in PROVEEDORES_MATERIALES:
        return jsonify({"error": "proveedor no reconocido o sin parser todavía"}), 404

    registros = _cotizaciones_material(id_proveedor)
    conteo: dict[str, int] = {}
    for r in registros:
        desc = r.get("DESCRIPCION")
        if desc:
            conteo[desc] = conteo.get(desc, 0) + 1

    curados = MATERIALES_CURADOS.get(id_proveedor)
    if curados:
        items = [{"descripcion": d, "cotizaciones": conteo.get(d, 0)} for d in curados]
    else:
        items = [{"descripcion": d, "cotizaciones": n} for d, n in sorted(conteo.items())]
    return jsonify(items)


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


def _curva_rem_interanual() -> tuple[str | None, list[dict]]:
    """Curva interanual completa (cualquier mes objetivo) del relevamiento
    MÁS RECIENTE — incluye tanto los "dic-YY" (año calendario completo) como
    los anclajes intermedios ("jun-YY", 12/24 meses hacia adelante)."""
    records = sheets.read_records(_sheet_id(), REM_INTERANUAL_TAB)
    if not records:
        return None, []
    ultima_fecha = max(r["FECHA_PRONOSTICO"] for r in records)
    curva = [
        {"PERIODO": r["PERIODO"], "MEDIANA": float(r["MEDIANA"])}
        for r in records if r["FECHA_PRONOSTICO"] == ultima_fecha
    ]
    return ultima_fecha, curva


@app.route("/api/rem/anual")
def get_rem_anual():
    """Solo el subconjunto "dic-YY" (año calendario completo) de la curva
    interanual — la vista simple "cuánto se espera para todo el año"."""
    relevamiento, curva = _curva_rem_interanual()
    anuales = [
        {"anio": int(c["PERIODO"][:4]), "mediana": c["MEDIANA"]}
        for c in curva if c["PERIODO"][5:7] == "12"
    ]
    return jsonify({"relevamiento": relevamiento, "curva": sorted(anuales, key=lambda a: a["anio"])})


@app.route("/api/rem/estimaciones")
def get_rem_estimaciones():
    """Curva mensual continua: dato real de INDEC donde existe, curva mensual
    explícita del REM donde el real todavía no llega, y para lo que ni uno
    ni otro cubren, reparte parejo (raíz N-ésima) contra las anclas
    interanuales del REM (dic/dic + 12/24 meses hacia adelante) — ver
    api/rem_estimaciones.py para el detalle del armado."""
    sid = _sheet_id()
    relevamiento_anual, curva_interanual = _curva_rem_interanual()
    if not curva_interanual:
        return jsonify({"error": "no hay REM interanual cargado todavía (correr refresh de rem)"}), 422

    _, curva_mensual_rem = _curva_rem_actual("ipc")
    inflacion_real = sheets.read_records(sid, "INFLACION_INDEC")

    reales = [{"PERIODO": r["FECHA"], "VALOR": r["VALOR"]} for r in inflacion_real]
    rem_mensual = [{"PERIODO": r["PERIODO"], "MEDIANA": r["MEDIANA"]} for r in curva_mensual_rem]

    curva = construir_curva_mensual(reales, rem_mensual, curva_interanual)
    resumen_anual = resumen_por_anio(curva, curva_interanual)

    return jsonify({
        "relevamiento_anual": relevamiento_anual,
        "curva": curva,
        "resumen_anual": resumen_anual,
    })


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

# Materiales puntuales elegibles como divisor en el selector de ajuste (ej.
# "hora de Oficial ÷ barra de hierro") — se toma el ÚLTIMO precio conocido
# de cada uno vía el mismo merge_asof que ya usa ajuste.py, sin importar que
# haya muchos más puntos de mano de obra que de material.
INDICES_MATERIALES = {
    "hierro": ("43", "HIERRO Aº TORS.Ø 10-BR X 12MT."),
    "cemento": ("43", "CEMENTO PORTLAND X 25 KG. (LOMA NEGRA)-25"),
    "ladrillo": ("43", "LADRILLO HUECO DE 1º 18X18X25-5"),
}


def _construir_indice_nivel(registros_pct: list[dict], fecha_col: str, valor_col: str, base: float = 100.0) -> list[dict]:
    """CER/UVA ya vienen como nivel acumulado (un valor tipo 806.99), pero
    INFLACION_INDEC solo tiene la variación % mensual — para poder usarlo
    como divisor en /api/ajustar (que asume un nivel, no un %) hay que
    encadenarlo en un índice propio (base 100 en la primera fecha de la
    serie, igual criterio que usaba Juan en su Excel)."""
    filas = sorted(registros_pct, key=lambda r: r[fecha_col])
    nivel = base
    resultado = []
    for r in filas:
        valor = r.get(valor_col)
        if valor in (None, ""):
            continue
        nivel *= (1 + float(valor) / 100)
        resultado.append({fecha_col: r[fecha_col], valor_col: round(nivel, 4)})
    return resultado


def _serie_indice(nombre_indice: str):
    """Devuelve (records, fecha_col, valor_col) para un nombre de índice elegible en el selector de ajuste."""
    if nombre_indice in ("cer", "uva"):
        cfg = SERIES[nombre_indice]
        return sheets.read_records(_sheet_id(), cfg["tab"]), cfg["fecha_col"], cfg["valor_col"]
    if nombre_indice == "ipc":
        cfg = SERIES["inflacion_indec"]
        registros_pct = sheets.read_records(_sheet_id(), cfg["tab"])
        nivel = _construir_indice_nivel(registros_pct, cfg["fecha_col"], cfg["valor_col"])
        return nivel, cfg["fecha_col"], cfg["valor_col"]
    if nombre_indice in DOLAR_COLUMNAS:
        return sheets.read_records(_sheet_id(), DOLAR_TAB), "FECHA", DOLAR_COLUMNAS[nombre_indice]
    if nombre_indice in INDICES_MATERIALES:
        id_prov, descripcion = INDICES_MATERIALES[nombre_indice]
        registros = _cotizaciones_material(id_prov, descripcion)
        return registros, "FECHA", "PRECIO"
    # Cualquier otra familia resoluble (ej. "salarios:INDICE_TOTAL",
    # "cac:COSTO_CONSTRUCCION") sirve también como divisor — para poder
    # armar ratios como "alquiler ÷ salario" o "alquiler ÷ costo de
    # construcción" sin duplicar la lógica de resolución.
    return _resolver_familia(nombre_indice)


def _resolver_familia(familia: str, item: str | None = None):
    """Devuelve (records, fecha_col, valor_col) para cualquier familia elegible:
      - "cer", "uocra", ...        -> serie propia de SERIES (una columna fija)
      - "construccion:MATERIALES"  -> columna elegida dentro de una hoja multi-columna
      - "cac:MANO_DE_OBRA"
      - "dolar:dolar_blue"         -> una cotización dentro de la hoja DOLAR
      - "mat:43" (+ item=...)       -> cotizaciones de un proveedor de Obra, filtradas
                                       opcionalmente a un material puntual (DESCRIPCION)
    Devuelve (None, None, None) si no se reconoce."""
    if familia in SERIES:
        cfg = SERIES[familia]
        return sheets.read_records(_sheet_id(), cfg["tab"]), cfg["fecha_col"], cfg["valor_col"]

    if ":" in familia:
        tipo, sub = familia.split(":", 1)

        if tipo in SERIES_MULTI_COLUMNA:
            cfg = SERIES_MULTI_COLUMNA[tipo]
            col = sub if sub in cfg["columnas"] else cfg["columnas"][0]
            return sheets.read_records(_sheet_id(), cfg["tab"]), cfg["fecha_col"], col

        if tipo == "dolar":
            col = DOLAR_COLUMNAS.get(sub)
            if not col:
                return None, None, None
            return sheets.read_records(_sheet_id(), DOLAR_TAB), "FECHA", col

        if tipo == "mat":
            registros = _cotizaciones_material(sub, item)
            return registros, "FECHA", "PRECIO"

    return None, None, None


@app.route("/api/ajustar")
def get_ajustado():
    familia = request.args.get("familia")
    indice = request.args.get("indice", "ninguno")
    item = request.args.get("item")

    base, base_fecha, base_valor = _resolver_familia(familia or "", item)
    if base is None:
        return jsonify({"error": f"familia desconocida: {familia}"}), 404

    if indice == "ninguno":
        resultado = ajustar(base, None, base_fecha, base_valor, modo="nominal")
    else:
        idx_records, idx_fecha, idx_valor = _serie_indice(indice)
        if idx_records is None:
            return jsonify({"error": f"índice desconocido: {indice}"}), 404
        resultado = ajustar(base, idx_records, base_fecha, base_valor, idx_fecha, idx_valor, modo="ratio")

    return jsonify(resultado)


# ── Resumen (MTD/YTD/1A/5A/TIR + variación entre dos fechas cualquiera) ─────

@app.route("/api/resumen")
def get_resumen():
    filas = []
    for nombre, familia in RESUMEN_SERIES:
        records, fecha_col, valor_col = _resolver_familia(familia)
        r = resumen_serie(records or [], fecha_col or "FECHA", valor_col or "VALOR")
        filas.append({"familia": familia, "nombre": nombre, **(r or {})})
    return jsonify(filas)


@app.route("/api/variacion")
def get_variacion():
    familia = request.args.get("familia")
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    if not (familia and desde and hasta):
        return jsonify({"error": "faltan parámetros: familia, desde, hasta (YYYY-MM-DD)"}), 400

    records, fecha_col, valor_col = _resolver_familia(familia)
    if records is None:
        return jsonify({"error": f"familia desconocida: {familia}"}), 404

    r = calcular_variacion(records, fecha_col, valor_col, desde, hasta)
    if r is None:
        return jsonify({"error": "no hay datos suficientes en ese rango"}), 422
    return jsonify(r)


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
    print(f"[scheduler] CAC +{n} filas (CAMARCO/cifrasonline no siempre tiene el último mes)")


def refrescar_salarios():
    sid = _sheet_id()
    serie = salarios.fetch_salarios()
    headers = ["FECHA", "PRIVADO_REGISTRADO", "PUBLICO", "TOTAL_REGISTRADO", "NO_REGISTRADO", "INDICE_TOTAL"]
    n = sheets.upsert_series(sid, "SALARIOS", headers, "FECHA", serie)
    print(f"[scheduler] SALARIOS +{n} filas")


def refrescar_icc():
    sid = _sheet_id()
    datos = icc.fetch_icc()
    headers = ["FECHA", "GENERAL", "MATERIALES", "MANO_DE_OBRA", "GASTOS"]
    for clave, serie in datos.items():
        n = sheets.upsert_series(sid, f"ICC_{clave}", headers, "FECHA", serie)
        print(f"[scheduler] ICC_{clave} +{n} filas")


def refrescar_alquileres():
    sid = _sheet_id()
    serie = alquileres.fetch_alquileres()
    headers = ["FECHA", "PRECIO_2_AMBIENTES", "PRECIO_3_AMBIENTES", "PROMEDIO"]
    n = sheets.upsert_series(sid, "ALQUILER_CABA", headers, "FECHA", serie)
    print(f"[scheduler] ALQUILER_CABA +{n} filas (fuente discontinuada, no pasa de ago-2019)")


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

    interanual = datos.get("ipc_interanual", [])
    for f in interanual:
        f["CLAVE"] = f"{f['FECHA_PRONOSTICO']}|{f['PERIODO']}"
    n2 = sheets.upsert_series(sid, REM_INTERANUAL_TAB, REM_INTERANUAL_HEADERS, "CLAVE", interanual)
    print(f"[scheduler] {REM_INTERANUAL_TAB} +{n2} filas")


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
    "salarios": refrescar_salarios,
    "icc": refrescar_icc,
    "alquileres": refrescar_alquileres,
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
    sched.add_job(refrescar_salarios, "interval", days=7)
    sched.add_job(refrescar_icc, "interval", days=7)

    # CAMARCO publica su dato del mes recién después del día 25 — antes de
    # eso pedirlo no trae nada nuevo. Se chequea dos veces por si el día 25
    # cae en fin de semana/feriado y el dato sale un poco más tarde.
    sched.add_job(refrescar_cac, "cron", day="26,28", hour=9)

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
