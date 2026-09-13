"""
INDEC — "Información estadística para la actualización de los precios de los
contratos de obra pública" (Decreto 1295/2002, Anexo Metodológico art. 15).

ESTA es la fuente de la redeterminación de precios, y no el ICC agregado: el
ICC publica cuatro capítulos (general, materiales, mano de obra, gastos
generales) y los decretos piden el índice del INSUMO —"acero aletado", "caños
de PVC", "alquiler de retroexcavadora"—. Ese detalle vive en un solo archivo,
que INDEC actualiza todos los meses:

    https://www.indec.gob.ar/ftp/cuadros/economia/op_icc_sipm_2016.xls

Nueve hojas, base dic-2015 = 100 (las del ICC arrancan en oct-2015 = 100):

    1, IPIB               IPIB por inciso del art. 15 (químicos, asfaltos, ...)
    2 y 3 IPIB apertura   IPIB a máxima apertura, por código CPC 2 — el catálogo
    4, ICC cont.          materiales del ICC con precio de referencia
    5, ICC                los incisos que se leen del ICC (mano de obra, etc.)
    6, Servicios          alquiler de camión, volquete, pala, retro
    7 y 8 Cap. M. Obra    oficial especializado / oficial / medio oficial / ayudante
    9, Equipos            guinche, hormigonera, vibrador, taladro
    10, Cap Gtos. Grales. agua, obrador, cerco, capataz, conexiones
    11 y 12 Cap. Mat.     ~240 materiales, uno por uno — el que engancha con el APU

⚠ Los archivos `SH-ICC-*.xls` del sitio viejo son el ARCHIVO HISTÓRICO: llegan
hasta 2015 y no se actualizan. Sirven para empalmar hacia atrás, no para
calcular una redeterminación de hoy.

El valor `s` (secreto estadístico) se guarda como None: el índice no existe ese
mes, y rellenarlo con el anterior sería inventar el número que define la plata.
"""

from __future__ import annotations

import datetime as dt
import io
import re

import requests
import xlrd

URL = "https://www.indec.gob.ar/ftp/cuadros/economia/op_icc_sipm_2016.xls"

MESES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
}

# Cada hoja arma el código de otra manera, y adivinarlo pegaba el CIIU con el
# CPC ("269537510-1") o se comía el inciso del decreto. Va declarado:
#   "cpc"      el código CPC viene partido en celdas contiguas: 37510 | - | 11
#   "inciso"   la fila la identifica el inciso del art. 15: a), b), ... w)
#   "apertura" col 1 = CIIU rev.3, col 2 = CPC 2 ya escrito entero
# hoja del .xls -> (clave corta, publicación de origen, modo)
HOJAS = {
    "1, IPIB":               ("IPIB_INCISOS",   "IPIB", "inciso"),
    "2 y 3 IPIB apertura":   ("IPIB_APERTURA",  "IPIB", "apertura"),
    "5, ICC":                ("ICC_INCISOS",    "ICC",  "inciso"),
    "6, Servicios":          ("ICC_SERVICIOS",  "ICC",  "cpc"),
    "7, y 8Cap. M. Obra":    ("ICC_MANO_OBRA",  "ICC",  "cpc"),
    "9, Equipos":            ("ICC_EQUIPOS",    "ICC",  "cpc"),
    "10, Cap Gtos. Grales.": ("ICC_GASTOS",     "ICC",  "cpc"),
    "11 y 12Cap. Mat.":      ("ICC_MATERIALES", "ICC",  "cpc"),
}


_ENCABEZADOS = {
    "descripción", "descripcion", "código", "codigo", "notas", "concepto",
    "conceptos", "aperturas", "apertura", "período", "periodo", "insumos",
    "clasificación", "clasificacion",
}


def _texto(v) -> str:
    if isinstance(v, float):
        return str(int(v)) if v == int(v) else str(v)
    return str(v or "").strip()


def _es_anio(v) -> int | None:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n if 1990 <= n <= 2100 else None


def _mes(v) -> int | None:
    t = _texto(v).lower().replace("*", "").strip()
    return MESES.get(t[:3]) if t else None


def _mapa_columnas(sh) -> tuple[dict[int, dt.date], dict[int, bool], int]:
    """Devuelve {columna: periodo}, {columna: provisorio} y la fila de datos."""
    fila_anios = None
    for r in range(min(20, sh.nrows)):
        anios = [c for c in range(sh.ncols) if _es_anio(sh.cell_value(r, c))]
        if len(anios) >= 3:
            fila_anios = r
            break
    if fila_anios is None:
        raise ValueError("no se encontró la fila de años")

    fila_meses = fila_anios + 1
    periodos: dict[int, dt.date] = {}
    provisorio: dict[int, bool] = {}
    anio_actual = None
    for c in range(sh.ncols):
        nuevo = _es_anio(sh.cell_value(fila_anios, c))
        if nuevo:
            anio_actual = nuevo
        mes = _mes(sh.cell_value(fila_meses, c))
        if anio_actual and mes:
            periodos[c] = dt.date(anio_actual, mes, 1)
            provisorio[c] = "*" in _texto(sh.cell_value(fila_meses, c))
    if not periodos:
        raise ValueError("no se pudo mapear ninguna columna a un período")
    return periodos, provisorio, fila_meses + 1


def _valor(v) -> float | None:
    if isinstance(v, float):
        return v
    t = _texto(v)
    if not t or t.lower() in {"s", "-", "..", "///"}:
        return None
    try:
        return float(t.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _celdas_texto(sh, r: int, hasta: int) -> list[tuple[int, str]]:
    return [(c, _texto(sh.cell_value(r, c)))
            for c in range(min(hasta, sh.ncols))
            if _texto(sh.cell_value(r, c))]


def _identificar(sh, r: int, primera_col_dato: int, modo: str) -> tuple[str, str, str, int]:
    """Devuelve (codigo, descripcion, clasificacion, nivel) de una fila."""
    celdas = _celdas_texto(sh, r, primera_col_dato)
    if not celdas:
        return "", "", "", 0

    if modo == "apertura":
        ciiu = next((t for c, t in celdas if c == 1), "")
        codigo = next((t for c, t in celdas if c == 2), "")
        desc = next((t for c, t in celdas if c >= 3), "")
        return codigo, desc, ciiu, 3

    if modo == "inciso":
        # col 0 = "a)" o "inciso e)"; col 1 = insumo; col 2 = cuadro; col 3 = apertura
        primera = celdas[0]
        if not re.search(r"^[a-z]\)|inciso", primera[1], re.IGNORECASE):
            return "", "", "", 0
        codigo = re.sub(r"^inciso\s*", "", primera[1], flags=re.IGNORECASE).strip()
        insumo = next((t for c, t in celdas if c == 1), "")
        apertura = next((t for c, t in celdas if c >= 3), "")
        return codigo, insumo or apertura, apertura, 3

    # modo "cpc": las piezas numéricas contiguas forman el código y la última
    # celda de texto es la descripción — su columna marca el nivel del árbol.
    piezas, descripciones = [], []
    for c, t in celdas:
        if re.fullmatch(r"[\d]+([-.][\d]+)*", t) or t == "-":
            piezas.append(t)
        else:
            descripciones.append((c, t))
    codigo = "".join(piezas).strip("-")
    if descripciones:
        col, desc = descripciones[-1]
        return codigo, desc, "", col
    return codigo, "", "", 0


def _seccion(sh, r: int, hasta: int) -> tuple[str, str] | None:
    """Las hojas del IPIB se dividen en NACIONALES / IMPORTADOS y, la de
    apertura, además en Cuadro 2 y Cuadro 3. El mismo código CPC aparece en
    las cuatro combinaciones con valores distintos —el inciso j) del decreto
    pide justamente el IMPORTADO— así que la sección es parte de la identidad."""
    celdas = _celdas_texto(sh, r, hasta)
    if len(celdas) != 1:
        return None
    t = celdas[0][1].upper()
    if t.startswith("NACIONALES"):
        return ("origen", "NACIONAL")
    if t.startswith("IMPORTADOS"):
        return ("origen", "IMPORTADO")
    m = re.match(r"CUADRO\s+(\d+)", t)
    if m:
        return ("cuadro", m.group(1))
    return None


def _leer_hoja(sh, clave: str, publicacion: str, modo: str) -> list[dict]:
    periodos, provisorio, fila_ini = _mapa_columnas(sh)
    primera_col_dato = min(periodos)
    filas: list[dict] = []
    origen, cuadro = "", ""
    for r in range(fila_ini):          # el "Cuadro N." de la hoja está arriba
        marca = _seccion(sh, r, primera_col_dato)   # del encabezado de períodos
        if marca and marca[0] == "cuadro":
            cuadro = marca[1]
    for r in range(fila_ini, sh.nrows):
        marca = _seccion(sh, r, primera_col_dato)
        if marca:
            if marca[0] == "origen":
                origen = marca[1]
            else:
                cuadro, origen = marca[1], ""
            continue
        codigo, desc, clasif, col_desc = _identificar(sh, r, primera_col_dato, modo)
        if not codigo and not desc:
            continue
        if desc.strip().lower() in _ENCABEZADOS:
            continue     # el segundo cuadro de la hoja repite su encabezado, y
                         # los años de esa fila se leen como si fueran índices
        if not codigo:
            # Los totales del árbol de mano de obra no tienen CPC (son la suma
            # de sus hijos). Se les arma una clave con el texto para que tengan
            # identidad estable entre publicaciones.
            codigo = "_" + re.sub(r"[^A-Z0-9]+", "_", desc.upper())[:40].strip("_")
        valores = {c: _valor(sh.cell_value(r, c)) for c in periodos}
        if not any(v is not None for v in valores.values()):
            continue  # nota al pie, título de bloque o fila entera con "s"
        for c, periodo in periodos.items():
            filas.append({
                "grupo": clave,
                "publicacion": publicacion,
                "codigo": codigo,
                "origen": origen,
                "cuadro": cuadro,
                "descripcion": desc,
                "clasificacion": clasif,
                "nivel": col_desc,
                "periodo": periodo.isoformat(),
                "indice": valores[c],
                "provisorio": provisorio[c],
            })
    return filas


def fetch(contenido: bytes | None = None) -> list[dict]:
    """Baja el .xls (o usa uno ya descargado) y lo devuelve en formato largo."""
    if contenido is None:
        r = requests.get(URL, timeout=120, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        contenido = r.content
    wb = xlrd.open_workbook(file_contents=contenido)
    filas: list[dict] = []
    for hoja, (clave, publicacion, modo) in HOJAS.items():
        if hoja not in wb.sheet_names():
            continue
        filas.extend(_leer_hoja(wb.sheet_by_name(hoja), clave, publicacion, modo))
    return filas


if __name__ == "__main__":
    import collections
    import sys

    contenido = open(sys.argv[1], "rb").read() if len(sys.argv) > 1 else None
    filas = fetch(contenido)
    por_grupo = collections.Counter(f["grupo"] for f in filas)
    conceptos = collections.defaultdict(set)
    for f in filas:
        conceptos[f["grupo"]].add((f["codigo"], f["descripcion"]))
    print(f"{len(filas)} filas")
    for g, n in por_grupo.items():
        print(f"  {g:16s} {len(conceptos[g]):4d} conceptos  {n:7d} filas")
    fechas = sorted({f["periodo"] for f in filas})
    print(f"  períodos: {fechas[0]} -> {fechas[-1]} ({len(fechas)})")
