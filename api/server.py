"""
Indices - API Server (Flask)

Mismo patrón que sibra-obra-repo/api/server.py: Flask + gspread (OAuth
desktop) + caché en memoria 90s + APScheduler para refrescar las fuentes
automáticas. Sirve también el frontend estático (index.html).

Fuentes, agrupadas por cadencia real (no por cómo las publica cada
organismo — varias de estas se "publican" a diario pero en el fondo
dependen de un único dato mensual, ver notas de cada grupo):

  DIARIO (mercado — cambian de verdad día a día):
    DOLAR, CAUCION, RIESGO_PAIS, MERVAL, BADLAR, TAMAR, BAIBAR, DEPOSITOS_30D,
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

import datetime as dt
import os
import sys
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db
import sheets
from ajuste import ajustar
from proyeccion import estimar_modelo, proyectar
from rem_estimaciones import construir_curva_mensual, resumen_por_anio
from resumen import resumen_serie
from resumen import variacion as calcular_variacion
from scrapers import alquileres, argentinadatos, bcra, bcra_rem, camarco, cauciones, dolares, icc, investing, mav, ripte, salarios, tim, uocra

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

# Cauciones en pesos (BYMA, tasa TNA %) — curva completa en vivo la sigue
# dando financiamiento.py (Vinculacion bancos, puerto 8300); acá se persiste
# el histórico de 4 plazos de referencia para poder graficarlo, mismo patrón
# que DOLAR (ver scrapers/cauciones.py).
CAUCION_TAB = "CAUCION"

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
    "caucion": {"tab": "CAUCION", "fecha_col": "FECHA",
                "columnas": ["TASA_1D", "TASA_7D", "TASA_14D", "TASA_30D"]},
    # Cheques/echeqs y pagarés de MAV: TNA de la punta corta de la curva, por
    # segmento y moneda. Pedido de Juan (2026-08-09): tenerlos siempre a la
    # vista, en pesos y en dólares. ⚠ **Cheques en dólares no existe en MAV**
    # (ver scrapers/mav.py), por eso la familia `cheques` solo tiene pesos.
    "cheques": {"tab": "CHEQUES", "fecha_col": "FECHA",
                "columnas": ["AVALADO_CORTO", "GARANTIZADO_CORTO", "NO_GARANTIZADO_CORTO"]},
    "pagares": {"tab": "PAGARES", "fecha_col": "FECHA",
                "columnas": ["AVALADO_CORTO", "GARANTIZADO_CORTO", "NO_GARANTIZADO_CORTO",
                             "AVALADO_CORTO_USD", "GARANTIZADO_CORTO_USD", "NO_GARANTIZADO_CORTO_USD",
                             "AVALADO_CORTO_DL", "GARANTIZADO_CORTO_DL", "NO_GARANTIZADO_CORTO_DL"]},
}

# Series que son TASAS (% anual), no índices de nivel. La distinción importa:
# la variación porcentual de una tasa engaña — BADLAR de 30 % a 35 % es
# "+16,7 %" pero son **+5 puntos**, y el número que se lee es el segundo.
# El Resumen las muestra en un bloque aparte, con variación en PUNTOS.
SERIES_TASAS = {
    "badlar", "baibar", "tamar", "depositos_30d", "adelantos_cta_cte",
    "prestamos_personales", "caucion", "cheques", "pagares",
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
    ("IPC (INDEC, índice)", "ipc_nivel"),
    ("CAMARCO costo construcción", "cac:COSTO_CONSTRUCCION"),
    ("CAMARCO materiales", "cac:MATERIALES"),
    ("CAMARCO mano de obra", "cac:MANO_DE_OBRA"),
    ("Construcción general (APYMECO)", "construccion:INDICE_GENERAL"),
    ("Índice de Salarios INDEC", "salarios:INDICE_TOTAL"),
    ("ICC Buenos Aires (costo construcción)", "icc_buenos_aires:GENERAL"),
    ("Alquiler CABA (promedio, fuente 2013-2019)", "alquiler_caba:PROMEDIO"),
    ("Riesgo país", "riesgo_pais"),
    ("MERVAL", "merval"),
    ("Caución 1 día", "caucion:TASA_1D"),
    ("Caución 7 días", "caucion:TASA_7D"),
    ("Caución 30 días", "caucion:TASA_30D"),
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


# Migración a Supabase (Fase 6, ver SIBRA_SERVER/PROCESO.md) — todas las tabs
# de "series_valores" (simples y anchas) ya viven en Postgres. REM,
# UOCRA_ADICIONALES y MATERIALES_HISTORICO tienen sus propias tablas (ver
# más abajo, no encajan en el formato genérico fecha/valor).
SERIES_SIMPLES_SUPABASE = {
    "CER", "UVA", "UVI", "ICL", "INFLACION_INDEC", "BADLAR", "TAMAR", "BAIBAR",
    "DEPOSITOS_30D", "ADELANTOS_CTA_CTE", "PRESTAMOS_PERSONALES", "TIM",
    "RIESGO_PAIS", "MERVAL",
}
SERIES_ANCHAS_SUPABASE = {
    "DOLAR", "UOCRA", "CONSTRUCCION", "CAC", "SALARIOS",
    "ICC_CABA", "ICC_BUENOS_AIRES", "ICC_CORDOBA", "ICC_SANTA_FE",
    "ALQUILER_CABA", "RIPTE", "CAUCION", "CHEQUES", "PAGARES",
}
SERIES_EN_SUPABASE = SERIES_SIMPLES_SUPABASE | SERIES_ANCHAS_SUPABASE
REM_EN_SUPABASE = True
UOCRA_ADICIONALES_EN_SUPABASE = True
MATERIALES_HISTORICO_EN_SUPABASE = True


def _leer(tab: str) -> list[dict]:
    """Lee una pestaña: de Postgres si ya fue migrada, sino de Sheets — mismo
    shape de salida en los dos casos, el resto del código no distingue."""
    if tab in SERIES_SIMPLES_SUPABASE:
        return db.leer_serie_simple(tab)
    if tab in SERIES_ANCHAS_SUPABASE:
        return db.leer_serie_ancha(tab)
    return sheets.read_records(_sheet_id(), tab)


def _guardar_simple(tab: str, rows: list[dict]) -> int:
    """rows = [{"FECHA":.., "VALOR":..}, ...]. Escribe en Postgres si la tab
    ya fue migrada, sino en Sheets — mismo comportamiento append-only en
    los dos casos (ON CONFLICT/upsert_series nunca corrigen, solo agregan)."""
    if tab in SERIES_SIMPLES_SUPABASE:
        return db.upsert_valores_simple(tab, rows)
    return sheets.upsert_series(_sheet_id(), tab, ["FECHA", "VALOR"], "FECHA", rows)


def _guardar_ancha(tab: str, headers: list[str], rows: list[dict]) -> int:
    """rows = [{"FECHA":.., col1:.., col2:.., ...}, ...] (headers sin "FECHA")."""
    if tab in SERIES_ANCHAS_SUPABASE:
        return db.upsert_valores_ancha_bulk(tab, rows, headers)
    return sheets.upsert_series(_sheet_id(), tab, ["FECHA"] + headers, "FECHA", rows)


# ── Series propias ──────────────────────────────────────────────────────────

@app.route("/api/series/<familia>")
def get_serie(familia):
    cfg = SERIES.get(familia)
    if not cfg:
        return jsonify({"error": f"familia desconocida: {familia}"}), 404
    records = _leer(cfg["tab"])
    return jsonify(records)


@app.route("/api/series/dolar")
def get_dolar():
    records = _leer(DOLAR_TAB)
    return jsonify(records)


@app.route("/api/series/caucion")
def get_caucion():
    records = _leer(CAUCION_TAB)
    return jsonify(records)


# ══ FINANCIAMIENTO — tasas en vivo, de BYMA y del MAV ═══════════════════════
# Juan, 2026-08-27: *«financiamiento va en Índices me parece»*.
#
# Tenía razón. Estas rutas vivían en el servicio 8300 y, al fusionarlo, pasaron
# un rato por el ERP — donde no van: el ERP registra lo que pasó con NUESTRA
# plata, y esto son precios de mercado, que es exactamente el dominio de
# Índices. Acá ya se refrescan cauciones (`refrescar_caucion`), MAV
# (`refrescar_mav`) y las series del BCRA.
#
# ⚠ QUEDA UNA DUPLICACIÓN ABIERTA, y conviene tenerla escrita: estas rutas
# consultan BYMA y el MAV EN VIVO, mientras `refrescar_*` guarda ese mismo dato
# en `mercado_curva_cauciones` y `mercado_tasas_mav`. Son dos caminos a lo
# mismo, y pueden dar distinto según cuándo corrió el scheduler. Lo correcto es
# que estas lean de las tablas y el vivo quede solo para el refresco — pero eso
# cambia lo que devuelven y no se hace de paso: queda anotado, no resuelto.
_FIN_DIR = Path(__file__).parent.parent.parent / "Vinculacion bancos" / "servicio"
if str(_FIN_DIR) not in sys.path:
    sys.path.insert(0, str(_FIN_DIR))


def _fin(fn):
    """Importa `financiamiento` recién al usarlo: ese módulo sale a la red, y
    arriba haría que Índices entero no arranque si BYMA o el MAV están caídos."""
    import importlib
    return getattr(importlib.import_module("financiamiento"), fn)


@app.route("/api/financiamiento/cauciones")
def fin_cauciones():
    """Curva de cauciones en pesos, en vivo desde BYMA (cache 5 min).
    ?plazo=7 devuelve solo la más cercana a ese plazo."""
    try:
        plazo = request.args.get("plazo", type=int)
        if plazo:
            return jsonify(_fin("caucion_a")(plazo) or {"error": "sin datos de BYMA ahora"})
        curva = _fin("curva_cauciones")()
        return jsonify(curva if curva is not None else {"error": "sin datos de BYMA ahora"})
    except Exception as e:
        return jsonify({"error": "financiamiento no disponible: %s" % str(e)[:120]}), 503


@app.route("/api/financiamiento/cauciones/texto")
def fin_cauciones_texto():
    """Texto listo para el bot de avisos (botón sin IA)."""
    try:
        return jsonify({"texto": _fin("texto_cauciones")()})
    except Exception as e:
        return jsonify({"error": str(e)[:120]}), 503


@app.route("/api/financiamiento/cauciones-mav")
def fin_cauciones_mav():
    """Plaza de caución del MAV: promedio/min/max/última + TEA + operaciones
    por plazo — más rica que el feed libre de BYMA."""
    try:
        d = _fin("curva_cauciones_mav")(request.args.get("moneda", "pesos"))
        return jsonify(d if d is not None else {"error": "sin datos de MAV ahora"})
    except Exception as e:
        return jsonify({"error": str(e)[:120]}), 503


@app.route("/api/financiamiento/bcra")
def fin_bcra():
    """Tasas de referencia bancarias (BCRA v4.0): plazo fijo 30d, BADLAR,
    TAMAR, adelantos, personales, política monetaria."""
    try:
        d = _fin("tasas_bcra")()
        return jsonify(d if d else {"error": "BCRA no responde ahora"})
    except Exception as e:
        return jsonify({"error": str(e)[:120]}), 503


@app.route("/api/financiamiento/texto")
def fin_texto():
    """Panorama completo (cauciones BYMA+MAV, cheques, pagarés, BCRA)."""
    try:
        return jsonify({"texto": _fin("texto_financiamiento")()})
    except Exception as e:
        return jsonify({"error": str(e)[:120]}), 503


# ⚠ ÚLTIMA de las de financiamiento: `<instrumento>` es comodín y se comería
# `/cauciones`, `/bcra` y `/texto` si se registrara antes.
@app.route("/api/financiamiento/<instrumento>")
def fin_instrumento(instrumento):
    """Tasas por plazo y segmento desde el MAV: cheques | pagares | fce.
    ?moneda=$ (default) o dol."""
    if instrumento not in ("cheques", "pagares", "fce"):
        return jsonify({"error": "instrumento debe ser cheques, pagares o fce"}), 404
    try:
        d = _fin("tasas_instrumento")(instrumento, request.args.get("moneda", "$"))
        return jsonify(d if d is not None else {"error": "sin datos de MAV ahora"})
    except Exception as e:
        return jsonify({"error": str(e)[:120]}), 503


@app.route("/api/series/cheques")
def get_cheques():
    return jsonify(_leer("CHEQUES"))


@app.route("/api/series/pagares")
def get_pagares():
    return jsonify(_leer("PAGARES"))


# ── Financiamiento: cheques, pagarés y caución, todo junto ──────────────────
#
# Pedido de Juan (2026-08-09): *"lo que quiero tener todo el tiempo es las
# tasas en pesos y dólares de cheques y pagarés avalados, garantizados y no
# avalados, las tasas de caución, y lo demás sí en tarjetas"*.
#
# Este endpoint arma las TARJETAS: el último valor de cada tasa **con la fecha
# de ese valor**. La fecha no es decorativa — si el job de MAV no corre, la
# tarjeta seguiría mostrando un número viejo como si fuera de hoy, que es
# exactamente cómo se envejecen los datos sin que nadie se entere.
#
# El histórico para graficar sale de `/api/series/{caucion,cheques,pagares}`.

_SEGMENTOS_CARD = [("AVALADO", "Avalado"), ("GARANTIZADO", "Garantizado"),
                   ("NO_GARANTIZADO", "No garantizado")]
_MONEDAS_CARD = [("", "Pesos"), ("_USD", "Dólares"), ("_DL", "Dólar linked")]

# Las tasas del BCRA, en el orden en que se leen juntas: primero lo que se
# paga por colocar, después lo que cuesta pedir. Ese contraste es la lectura
# útil — el spread entre las dos puntas.
_TASAS_BCRA = [
    ("badlar", "BADLAR (plazo fijo mayorista)"),
    ("baibar", "BAIBAR (interbancaria)"),
    ("tamar", "TAMAR (mayorista, plazos largos)"),
    ("depositos_30d", "Plazo fijo 30 días (minorista)"),
    ("adelantos_cta_cte", "Adelantos en cuenta corriente"),
    ("prestamos_personales", "Préstamos personales"),
]
# ⚠ **TIM no va acá.** Se llama "Tasa de Intereses Moratorios" y parece una
# tasa, pero la serie que publica el BCRA es un **coeficiente acumulado con
# base 03/06/1993 = 1** — hoy vale ~161.660. Puesto como tarjeta de TNA
# mostraba "161.660,14 %". Se usa como el CER: coeficiente de una fecha
# dividido el de otra, para calcular intereses moratorios entre dos fechas.
# Va con los índices de nivel, no con las tasas.


def _ultimo_por_columna(tab):
    """{columna: (valor, fecha)} con el último valor NO vacío de cada columna,
    cada uno con SU fecha.

    No alcanza con tomar la última fila entera: un día puede haber operado solo
    el plazo de 1 día, y entonces las otras columnas aparecerían "sin dato"
    aunque tengan un valor de la semana pasada. Cada tasa trae su propia fecha
    y la tarjeta la muestra — un número viejo se puede usar sabiendo que es
    viejo; uno viejo disfrazado de actual, no.
    """
    ultimos = {}
    for r in sorted(_leer(tab) or [], key=lambda x: str(x.get("FECHA") or "")):
        fecha = r.get("FECHA")
        for k, v in r.items():
            if k != "FECHA" and v not in (None, ""):
                ultimos[k] = (v, fecha)
    return ultimos


@app.route("/api/financiamiento")
def get_financiamiento():
    salida = {}

    # Cheques y pagarés: segmento × moneda. Solo se listan las monedas que ese
    # instrumento acepta de verdad — cheques en dólares NO existe en MAV, y es
    # mejor no mostrar la columna que mostrarla siempre vacía.
    for familia, tab in (("cheques", "CHEQUES"), ("pagares", "PAGARES")):
        ultimos = _ultimo_por_columna(tab)
        cols = SERIES_MULTI_COLUMNA[familia]["columnas"]
        bloques = []
        for sufijo, etiqueta_moneda in _MONEDAS_CARD:
            tasas = []
            for seg, etiqueta in _SEGMENTOS_CARD:
                col = f"{seg}_CORTO{sufijo}"
                if col not in cols:
                    continue
                v, f = ultimos.get(col, (None, None))
                tasas.append({"segmento": etiqueta, "columna": col, "fecha": f,
                              "tna": float(v) if v not in (None, "") else None})
            if tasas:
                bloques.append({"moneda": etiqueta_moneda, "sufijo": sufijo, "tasas": tasas})
        salida[familia] = {"monedas": bloques}

    # Caución: por plazo. El histórico lo guarda Índices; la curva completa en
    # vivo (~83 plazos) la sirve Tesorería en el 8300 — son complementarios.
    ultimos = _ultimo_por_columna(CAUCION_TAB)
    plazos = []
    for col in SERIES_MULTI_COLUMNA["caucion"]["columnas"]:
        v, f = ultimos.get(col, (None, None))
        n = col.replace("TASA_", "").replace("D", "")
        plazos.append({"plazo": f"{n} día" + ("" if n == "1" else "s"),
                       "columna": col, "fecha": f,
                       "tna": float(v) if v not in (None, "") else None})
    salida["caucion"] = {"plazos": plazos}

    # El resto de las tasas — las del BCRA. Estaban cargadas desde hace años
    # (BADLAR y BAIBAR desde 2001, adelantos desde 2009, TIM desde 1993) y
    # **no se veían en ninguna pantalla**: ni ventana propia ni fila en el
    # Resumen. Juan lo notó el 2026-08-09.
    bcra_tasas = []
    for familia, etiqueta in _TASAS_BCRA:
        tab = SERIES[familia]["tab"]
        recs = sorted((_leer(tab) or []), key=lambda x: str(x.get("FECHA") or ""))
        ult = next((r for r in reversed(recs)
                    if r.get(SERIES[familia]["valor_col"]) not in (None, "")), None)
        bcra_tasas.append({
            "familia": familia, "nombre": etiqueta,
            "fecha": ult.get("FECHA") if ult else None,
            "tna": float(ult[SERIES[familia]["valor_col"]]) if ult else None,
        })
    salida["bcra"] = {"tasas": bcra_tasas}
    return jsonify(salida)


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
    if MATERIALES_HISTORICO_EN_SUPABASE:
        historico = db.leer_materiales_historico(id_proveedor)
    else:
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
    records = db.leer_rem(tipo) if REM_EN_SUPABASE else sheets.read_records(_sheet_id(), tab)
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
    records = db.leer_rem("ipc_interanual") if REM_EN_SUPABASE else sheets.read_records(_sheet_id(), REM_INTERANUAL_TAB)
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
    inflacion_real = _leer("INFLACION_INDEC")

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

    cfg = SERIES[familia]
    objetivo = _leer(cfg["tab"])
    cer = _leer("CER")
    dolar = _leer(DOLAR_TAB)

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
        return _leer(cfg["tab"]), cfg["fecha_col"], cfg["valor_col"]
    if nombre_indice == "ipc":
        return _resolver_familia("ipc_nivel")
    if nombre_indice in DOLAR_COLUMNAS:
        return _leer(DOLAR_TAB), "FECHA", DOLAR_COLUMNAS[nombre_indice]
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
      - "ipc_nivel"                 -> IPC (INDEC) encadenado a nivel (base 100), igual
                                       criterio que CER/UVA/UOCRA — para poder comparar
                                       visualmente contra dólar/CAMARCO/APYMECO/salarios,
                                       no solo usarlo como divisor
    Devuelve (None, None, None) si no se reconoce."""
    if familia == "ipc_nivel":
        cfg = SERIES["inflacion_indec"]
        registros_pct = _leer(cfg["tab"])
        nivel = _construir_indice_nivel(registros_pct, cfg["fecha_col"], cfg["valor_col"])
        return nivel, cfg["fecha_col"], cfg["valor_col"]

    if familia in SERIES:
        cfg = SERIES[familia]
        return _leer(cfg["tab"]), cfg["fecha_col"], cfg["valor_col"]

    if ":" in familia:
        tipo, sub = familia.split(":", 1)

        if tipo in SERIES_MULTI_COLUMNA:
            cfg = SERIES_MULTI_COLUMNA[tipo]
            col = sub if sub in cfg["columnas"] else cfg["columnas"][0]
            return _leer(cfg["tab"]), cfg["fecha_col"], col

        if tipo == "dolar":
            col = DOLAR_COLUMNAS.get(sub)
            if not col:
                return None, None, None
            return _leer(DOLAR_TAB), "FECHA", col

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


# ── Publicación diaria del Resumen ──────────────────────────────────────────
# Snapshot por día del Resumen, para alimentar la página pública.
#
# 2026-08-02: **va a Supabase, ya no a la Sheet pública.** Decisión de Juan al
# ver que el front se publica por Vercel: un estático puede leer Supabase
# directo con la *publishable key* — mismo patrón que ya usa Market Suite
# (login Supabase Auth + RLS, establecido 2026-07-29). Ventajas concretas:
#   - el dato sale **en vivo**; la Sheet mostraba la foto del último job
#   - se cae una dependencia de OAuth (el token vence cada 7 días en Testing)
#   - desaparece un paso que podía fallar callado
# Drive queda SOLO para el backup periódico de la regla de 2 años
# (RETENCION_DATOS.md), no como camino de publicación.
#
# `indices_resumen_publico` es la ÚNICA tabla con policy de lectura para
# `anon`. El resto del negocio no se expone: el front usa la publishable key,
# nunca la service_role.
PUBLICO_RESUMEN_COLS = [
    "clave", "fecha_publicacion", "familia", "nombre",
    "ultimo_valor", "ultima_fecha", "mom", "d30", "ytd", "yoy", "yoy_anualizada", "a5",
]


def publicar_resumen():
    hoy = dt.date.today().isoformat()

    filas = []
    for nombre, familia in RESUMEN_SERIES:
        records, fecha_col, valor_col = _resolver_familia(familia)
        r = resumen_serie(records or [], fecha_col or "FECHA", valor_col or "VALOR")
        if not r:
            continue
        r = {k.lower(): v for k, v in r.items()}
        filas.append({
            "clave": f"{hoy}|{familia}", "fecha_publicacion": hoy,
            "familia": familia, "nombre": nombre,
            **{c: r.get(c) for c in PUBLICO_RESUMEN_COLS[4:]},
        })

    n = db.upsert_resumen_publico(filas)
    print(f"[scheduler] RESUMEN público: {n} filas en Supabase (indices_resumen_publico)")


@app.route("/api/variacion")
def get_variacion():
    familia = request.args.get("familia")
    indice = request.args.get("indice")  # opcional: mismo "ajuste" que ya está graficado (ej. "ipc", "cer")
    item = request.args.get("item")
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    if not (familia and desde and hasta):
        return jsonify({"error": "faltan parámetros: familia, desde, hasta (YYYY-MM-DD)"}), 400

    records, fecha_col, valor_col = _resolver_familia(familia, item)
    if records is None:
        return jsonify({"error": f"familia desconocida: {familia}"}), 404

    if indice and indice != "ninguno":
        idx_records, idx_fecha, idx_valor = _serie_indice(indice)
        if idx_records is None:
            return jsonify({"error": f"índice desconocido: {indice}"}), 404
        # La calculadora tiene que operar sobre la MISMA serie que está
        # graficada (ej. "cemento ÷ IPC"), no sobre el precio nominal del
        # cemento — se arma primero el ratio (igual que /api/ajustar) y
        # recién ahí se busca el valor "asof" en cada fecha pedida.
        records = ajustar(records, idx_records, fecha_col, valor_col, idx_fecha, idx_valor, modo="ratio")
        fecha_col, valor_col = "fecha", "valor"

    r = calcular_variacion(records, fecha_col, valor_col, desde, hasta)
    if r is None:
        return jsonify({"error": "no hay datos suficientes en ese rango"}), 422
    return jsonify(r)


# ── Refresh manual + scheduler ──────────────────────────────────────────────

def _refrescar_series_bcra(lista):
    for tab, fetch_fn in lista:
        serie = fetch_fn()
        rows = [{"FECHA": r["fecha"], "VALOR": r["valor"]} for r in serie]
        n = _guardar_simple(tab, rows)
        print(f"[scheduler] {tab} +{n} filas")


def refrescar_bcra_diarias():
    _refrescar_series_bcra(SERIES_BCRA_DIARIAS)


def refrescar_bcra_mensuales():
    _refrescar_series_bcra(SERIES_BCRA_MENSUALES)


def refrescar_tim():
    serie = tim.fetch_tim()
    n = _guardar_simple("TIM", serie)
    print(f"[scheduler] TIM +{n} filas")


def refrescar_riesgo_pais():
    serie = argentinadatos.fetch_riesgo_pais()
    n = _guardar_simple("RIESGO_PAIS", serie)
    print(f"[scheduler] RIESGO_PAIS +{n} filas")


def refrescar_merval():
    serie = investing.fetch_merval()
    n = _guardar_simple("MERVAL", serie)
    print(f"[scheduler] MERVAL +{n} filas")


def refrescar_cac():
    serie = camarco.fetch_cac()
    headers = ["COSTO_CONSTRUCCION", "MATERIALES", "MANO_DE_OBRA"]
    n = _guardar_ancha("CAC", headers, serie)
    print(f"[scheduler] CAC +{n} filas (CAMARCO/cifrasonline no siempre tiene el último mes)")


def refrescar_salarios():
    serie = salarios.fetch_salarios()
    headers = ["PRIVADO_REGISTRADO", "PUBLICO", "TOTAL_REGISTRADO", "NO_REGISTRADO", "INDICE_TOTAL"]
    n = _guardar_ancha("SALARIOS", headers, serie)
    print(f"[scheduler] SALARIOS +{n} filas")


def refrescar_icc():
    datos = icc.fetch_icc()
    headers = ["GENERAL", "MATERIALES", "MANO_DE_OBRA", "GASTOS"]
    for clave, serie in datos.items():
        n = _guardar_ancha(f"ICC_{clave}", headers, serie)
        print(f"[scheduler] ICC_{clave} +{n} filas")


def refrescar_alquileres():
    serie = alquileres.fetch_alquileres()
    headers = ["PRECIO_2_AMBIENTES", "PRECIO_3_AMBIENTES", "PROMEDIO"]
    n = _guardar_ancha("ALQUILER_CABA", headers, serie)
    print(f"[scheduler] ALQUILER_CABA +{n} filas (fuente discontinuada, no pasa de ago-2019)")


def refrescar_uocra():
    headers = [
        "OFICIAL_ESPECIALIZADO", "OFICIAL", "MEDIO_OFICIAL", "AYUDANTE", "SERENO",
        "OFICIAL_ESPECIALIZADO_NO_REM", "OFICIAL_NO_REM", "MEDIO_OFICIAL_NO_REM",
        "AYUDANTE_NO_REM", "SERENO_NO_REM",
    ]
    serie = uocra.fetch_uocra()
    n = _guardar_ancha("UOCRA", headers, serie)
    print(f"[scheduler] UOCRA +{n} filas (algunos meses solo salen como PDF escaneado, sin OCR quedan para carga manual; "
          f"no remunerativo no siempre se puede leer por formato inconsistente del PDF fuente)")

    adicionales = uocra.fetch_adicionales_76_75()
    if UOCRA_ADICIONALES_EN_SUPABASE:
        n2 = db.upsert_uocra_adicionales_bulk(adicionales)
    else:
        adic_headers = ["CLAVE", "CONCEPTO", "VALOR", "UNIDAD", "DESDE", "HASTA"]
        n2 = sheets.upsert_series(_sheet_id(), "UOCRA_ADICIONALES", adic_headers, "CLAVE", adicionales)
    print(f"[scheduler] UOCRA_ADICIONALES +{n2} filas (aporte solidario + contribución empresarial, solo 76/75)")


def refrescar_dolar():
    fila = dolares.fetch_actual()
    headers = ["OFICIAL_COMPRA", "OFICIAL_VENTA", "BLUE_COMPRA", "BLUE_VENTA",
               "MEP_COMPRA", "MEP_VENTA", "CCL_COMPRA", "CCL_VENTA",
               "MAYORISTA_COMPRA", "MAYORISTA_VENTA", "CRIPTO_COMPRA", "CRIPTO_VENTA",
               "TARJETA_COMPRA", "TARJETA_VENTA"]
    n = _guardar_ancha(DOLAR_TAB, headers, [fila])
    print(f"[scheduler] DOLAR +{n} filas")


def refrescar_caucion():
    # Un solo fetch a BYMA alimenta las dos tablas: el histórico de 4 plazos
    # de referencia (series_valores/CAUCION) y la foto completa en vivo
    # (mercado_curva_cauciones, se pisa entera — no es histórico).
    curva = cauciones.curva_completa()
    fila = cauciones.referencia_desde_curva(curva)
    n = _guardar_ancha(CAUCION_TAB, list(cauciones.PLAZOS_REFERENCIA), [fila])
    m = db.guardar_curva_cauciones(curva)
    print(f"[scheduler] CAUCION +{n} filas históricas, curva completa {m} plazos")


def refrescar_mav():
    # Un fetch por instrumento Y por moneda (cheques y pagarés tienen segmentos
    # distintos, no hay que mezclarlos al elegir la referencia de plazo corto)
    # — el snapshot completo (mercado_tasas_mav) junta todo, el histórico va
    # separado por instrumento a series_valores/CHEQUES y /PAGARES.
    #
    # ⚠ Los headers salen de `columnas_posibles`, no de lo que vino hoy: si un
    # día no opera el segmento 'garantizado', la columna tiene que seguir
    # existiendo o la serie ancha se desarma.
    #
    # 📌 Pedido de Juan (2026-08-09): tener siempre a la vista cheques y
    # pagarés en pesos Y en dólares, por segmento. **Cheques en dólares no
    # existe en MAV** — ver el docstring de `scrapers/mav.py`.
    todas = []
    for instrumento, (tab, monedas) in mav.INSTRUMENTOS.items():
        filas = []
        for moneda in monedas:
            filas += mav.tasas_instrumento(instrumento, moneda)
        todas += filas
        fila_ref = mav.referencia_por_segmento(filas)
        if not fila_ref:
            print(f"[scheduler] {tab} sin datos hoy (fin de semana o feriado)")
            continue
        cols = mav.columnas_posibles(instrumento)
        n = _guardar_ancha(tab, cols, [fila_ref])
        vistos = [c for c in fila_ref if c != "FECHA"]
        print(f"[scheduler] {tab} +{n} filas históricas ({', '.join(vistos)})")
    n = db.guardar_tasas_mav(todas)
    print(f"[scheduler] MAV (cheques/pagarés) {n} filas snapshot")


def backfill_mav(desde: str, hasta: str | None = None) -> dict:
    """Rellena el histórico de CHEQUES y PAGARES pegándole a MAV día por día.

    Se puede porque la API acepta `fecha` para días pasados — relevado el
    2026-08-09, hay al menos dos años disponibles. Antes se creía que era una
    foto irrecuperable del día, y por eso la serie tenía 6 filas.

    Es LENTO a propósito (pausa entre requests): son ~250 días hábiles por año
    y por instrumento. Correrlo una vez, no dejarlo en el scheduler.
    """
    d0 = dt.date.fromisoformat(desde)
    d1 = dt.date.fromisoformat(hasta) if hasta else dt.date.today()
    salida = {}
    for instrumento, (tab, _monedas) in mav.INSTRUMENTOS.items():
        filas = mav.serie_diaria(instrumento, d0, d1)
        n = _guardar_ancha(tab, mav.columnas_posibles(instrumento), filas) if filas else 0
        salida[tab] = {"dias_con_dato": len(filas), "guardadas": n}
        print(f"[backfill] {tab}: {len(filas)} días con dato, {n} guardadas")
    return salida


def backfill_caucion_desde_brokers() -> dict:
    """Rellena el histórico de CAUCION con la tasa REALMENTE pagada, sacada de
    las operaciones de `public.brokers_cauciones`.

    Por qué hace falta: BYMA devuelve **la curva de hoy**, no una serie. El job
    corrió tres días de julio y quedaron 12 filas — y lo no capturado no se
    puede recuperar de BYMA. Pero las cauciones propias sí están guardadas
    desde abril de 2024, con capital, interés y plazo, así que la TNA sale de
    ahí:

        TNA = interes / capital * 365 / (vencimiento - inicio) * 100

    ⚠ Es una tasa **distinta** a la de BYMA: es la que Sibra pagó, no la de
    referencia del mercado. Se guarda en las mismas columnas de plazo porque
    responde la misma pregunta ("a cuánto estaba la caución"), pero conviene
    saber de dónde salió cada tramo — el de BYMA es de fines de julio de 2026.

    Filtro: plazo 1-40 días e interés > 0. Sin eso entran las operaciones que
    vencen el mismo día (plazo 0 → la fórmula explota: aparecen TNAs de 40.000 %).
    """
    if not os.environ.get("SUPABASE_DB_URL"):
        return {"error": "falta SUPABASE_DB_URL — esta serie sale de Supabase, "
                         "no de Sheets"}
    # Cada operación cae en el plazo de referencia más cercano por abajo, así
    # una caución de 3 días alimenta TASA_1D y no TASA_30D.
    sql = """
        with base as (
          select start_date::date d,
                 (maturity_date::date - start_date::date) plazo,
                 capital::numeric cap, interest::numeric intr
            from public.brokers_cauciones
           where currency = 'ARS'
             and capital  ~ '^[0-9.]+$'
             and interest ~ '^-?[0-9.]+$'
        ), ok as (
          select d, plazo, (intr / nullif(cap, 0)) * 365.0 / plazo * 100 tna
            from base
           where plazo between 1 and 40 and cap > 0 and intr > 0
        ), clasificada as (
          select d,
                 case when plazo <= 3  then 'TASA_1D'
                      when plazo <= 10 then 'TASA_7D'
                      when plazo <= 20 then 'TASA_14D'
                      else 'TASA_30D' end col,
                 tna
            from ok
        )
        select d::text fecha, col,
               round(percentile_cont(0.5) within group (order by tna)::numeric, 2) tna
          from clasificada
         group by d, col
         order by d
    """
    por_fecha = {}
    with db.psycopg.connect(os.environ["SUPABASE_DB_URL"],
                            row_factory=db.dict_row) as con:
        for r in con.execute(sql):
            por_fecha.setdefault(r["fecha"], {"FECHA": r["fecha"]})[r["col"]] = float(r["tna"])
    filas = [por_fecha[f] for f in sorted(por_fecha)]
    n = _guardar_ancha(CAUCION_TAB, list(cauciones.PLAZOS_REFERENCIA), filas) if filas else 0
    print(f"[backfill] CAUCION desde brokers_cauciones: {len(filas)} días, {n} guardadas")
    return {"dias": len(filas), "guardadas": n,
            "desde": filas[0]["FECHA"] if filas else None,
            "hasta": filas[-1]["FECHA"] if filas else None}


@app.post("/api/backfill/caucion")
def post_backfill_caucion():
    """Histórico de caución a partir de las operaciones propias de brokers."""
    return jsonify(backfill_caucion_desde_brokers())


@app.post("/api/backfill/mav")
def post_backfill_mav():
    """Backfill del histórico de cheques/pagarés. `?desde=YYYY-MM-DD[&hasta=]`.
    Tarda minutos: es un request por día hábil y por moneda."""
    desde = request.args.get("desde")
    if not desde:
        return jsonify({"error": "falta ?desde=YYYY-MM-DD"}), 400
    try:
        return jsonify(backfill_mav(desde, request.args.get("hasta")))
    except ValueError as e:
        return jsonify({"error": f"fecha inválida: {e}"}), 400


def refrescar_ripte():
    serie = ripte.fetch_serie()
    n = _guardar_ancha("RIPTE", ["RIPTE", "VARIACION_MENSUAL"], serie)
    print(f"[scheduler] RIPTE +{n} filas")


def refrescar_rem():
    sid = _sheet_id()
    datos = bcra_rem.fetch_rem()
    for tipo, tab in REM_TABS.items():
        filas = datos.get(tipo, [])
        if REM_EN_SUPABASE:
            n = db.upsert_rem_bulk(tipo, filas)
        else:
            for f in filas:
                f["CLAVE"] = f"{f['FECHA_PRONOSTICO']}|{f['PERIODO']}"
            n = sheets.upsert_series(sid, tab, REM_HEADERS, "CLAVE", filas)
        print(f"[scheduler] {tab} +{n} filas")

    interanual = datos.get("ipc_interanual", [])
    if REM_EN_SUPABASE:
        n2 = db.upsert_rem_bulk("ipc_interanual", interanual)
    else:
        for f in interanual:
            f["CLAVE"] = f"{f['FECHA_PRONOSTICO']}|{f['PERIODO']}"
        n2 = sheets.upsert_series(sid, REM_INTERANUAL_TAB, REM_INTERANUAL_HEADERS, "CLAVE", interanual)
    print(f"[scheduler] {REM_INTERANUAL_TAB} +{n2} filas")


FUENTES_MANUALES = {
    "bcra_diarias": refrescar_bcra_diarias,
    "bcra_mensuales": refrescar_bcra_mensuales,
    "dolar": refrescar_dolar,
    "caucion": refrescar_caucion,
    "mav": refrescar_mav,
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
    "publicar_resumen": publicar_resumen,
}


@app.route("/api/refrescar/<fuente>", methods=["POST"])
def refrescar_manual(fuente):
    fn = FUENTES_MANUALES.get(fuente)
    if not fn:
        return jsonify({"error": f"fuente desconocida: {fuente} (usar: {', '.join(FUENTES_MANUALES)})"}), 404
    fn()
    return jsonify({"status": "ok"})


# Estado de la sincronización inicial. El front lo consulta para refrescar solo
# cuando entraron datos nuevos (antes el server no abría el puerto hasta terminar
# de sincronizar TODO, y parecía colgado varios minutos).
SYNC_INICIAL = {"listo": False, "hechas": 0, "total": 0, "actual": None}


def iniciar_scheduler():
    SYNC_INICIAL["total"] = len(FUENTES_MANUALES)
    for nombre, fn in FUENTES_MANUALES.items():
        SYNC_INICIAL["actual"] = nombre
        try:
            fn()
        except Exception as exc:
            print(f"[scheduler] primer refresh de {nombre} falló: {exc}")
        SYNC_INICIAL["hechas"] += 1
    SYNC_INICIAL["actual"] = None
    SYNC_INICIAL["listo"] = True
    print("[scheduler] sincronización inicial completa")

    sched = BackgroundScheduler(timezone="America/Argentina/Buenos_Aires")

    # Diario — mercado, cambia de verdad día a día
    sched.add_job(refrescar_bcra_diarias, "interval", hours=6)
    sched.add_job(refrescar_dolar, "interval", hours=4)
    sched.add_job(refrescar_caucion, "interval", hours=4)
    sched.add_job(refrescar_mav, "interval", hours=4)
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

    # Diario — foto de la pantalla Resumen a la Sheet pública (después de que
    # ya corrieron los refrescos del día, para llevarse el dato más nuevo).
    sched.add_job(publicar_resumen, "cron", hour=21)

    sched.start()
    return sched


# ── Frontend estático ────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/api/estado-sync")
def estado_sync():
    """Progreso de la sincronización inicial. El front lo consulta para refrescar
    la vista cuando terminan de entrar los datos nuevos."""
    return jsonify(SYNC_INICIAL)


@app.get("/api/uso-supabase")
def uso_supabase():
    """KPI de uso de la base (plan free = 500 MB) para anticipar el límite."""
    try:
        return jsonify(db.uso_supabase())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def schedulers_propios_activos():
    """¿Este proceso tiene que correr su propio scheduler?

    📝 **2026-08-11.** Hasta hoy Índices arrancaba SIEMPRE con 15 jobs adentro
    del proceso (dólar c/4h, BCRA c/6h, caución c/4h, REM semanal…). Eso hacía
    que "prender el server" y "poner a correr 15 trabajos" fueran la misma
    acción, sin forma de separarlas.

    ⚠ Y se pisaba con la consola: los 15 jobs `indices_*` del cronograma
    (`SIBRA_SERVER/panel`) le pegan a `POST /api/refrescar/<fuente>` — el mismo
    trabajo, por otro camino. Con los dos prendidos, cada fuente se refresca
    dos veces.

    Criterio de Juan (2026-08-11): el servidor sirve datos; **qué corre y
    cuándo lo decide la consola**, así no está corriendo todo el tiempo todo.

        SIBRA_SCHEDULERS=on   los corre este proceso (la PC, sin consola)
        (sin la variable)     NO los corre — manda el cronograma

    Por eso el default es NO: en Oracle es lo que corresponde, y si alguien
    levanta el server a mano tampoco dispara 15 trabajos sin querer.
    """
    return os.environ.get("SIBRA_SCHEDULERS", "").strip().lower() in ("1", "on", "true", "si")


if __name__ == "__main__":
    import threading
    port = int(os.environ.get("FLASK_PORT", 8100))
    if schedulers_propios_activos():
        # La sincronización inicial va en segundo plano: el server queda
        # disponible al instante y los datos van entrando mientras tanto.
        threading.Thread(target=iniciar_scheduler, daemon=True).start()
        print("[server] schedulers PROPIOS activos (SIBRA_SCHEDULERS=on)")
    else:
        print("[server] schedulers propios APAGADOS — los dispara la consola "
              "(panel 8400). Para correrlos acá: SIBRA_SCHEDULERS=on")
    print(f"[server] escuchando en http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
