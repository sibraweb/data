# -*- coding: utf-8 -*-
"""Tasas del Banco de la Nación: activa, pasiva y descubierto.

Juan, 2026-09-11: *«también me gustaría ir teniendo la tasa activa, la tasa
pasiva y la tasa de descubierto del Nación relevada»*.

⚠⚠ EL BNA NO PUBLICA HISTÓRICO — PUBLICA "LO VIGENTE HOY".
Los PDF de bna.com.ar son una foto: dicen qué tasa rige y desde cuándo, y nada
más. No hay serie para bajar. Por eso esto es un RELEVAMIENTO: se saca la foto
todos los días y la serie la construimos nosotros. El día que no corra el job,
ese día no existe — y no se puede recuperar después.

⚠ LA «TASA DE CARTERA GENERAL» ES LA TACG, la que faltaba para el tramo
01/01/2018 → 05/12/2018 del índice de certificados (ver
`api/descuento_certificados.py`). Relevarla desde hoy NO llena aquel hueco
—eso ya pasó y no hay de dónde sacarlo— pero sí garantiza que no se vuelva a
abrir: si mañana el BNA vuelve a parar un régimen sobre la cartera general,
vamos a tener la serie.

⚠ LOS NOMBRES DE ARCHIVO LLEVAN UN CORRELATIVO QUE CAMBIA. Hoy es
`tasas_cart_3970.pdf`; la semana pasada era otro número. Por eso los links se
DESCUBREN desde la página, no se hardcodean. Un número fijo funciona hasta que
deja de funcionar, y falla callado devolviendo un 404 o un PDF viejo.

⚠ EL PDF SE LEE POR COORDENADAS, NO POR ORDEN DE LÍNEAS. Las filas largas
parten el renglón (el concepto queda en y=453 y sus números en y=452) y hay
filas en blanco entre bloques. Leer "todos los conceptos y después todos los
números" desalinea la tabla y le pone a una tasa el nombre de otra — que es el
peor error posible acá, porque el número sigue siendo verosímil.
"""
from __future__ import annotations

import datetime as dt
import io
import re
import unicodedata

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PAGINA = "https://www.bna.com.ar/home/informacionalusuariofinanciero"
BASE = "https://www.bna.com.ar"
UA = {"User-Agent": "Mozilla/5.0"}

# Qué renglón del PDF va a qué serie. La clave se compara NORMALIZADA (sin
# acentos, sin mayúsculas, espacios colapsados) contra el concepto del PDF.
#
# ⚠ Se piden por nombre exacto y no por posición: el BNA agrega y saca renglones
# (aparecieron los "(Mi Banco)" y los "Reg Nº 822"). Por posición, un renglón
# nuevo arriba corre todo lo de abajo.
CONCEPTOS = {
    "tasa de cartera general (tasa de referencia)": "BNA_CARTERA_GENERAL",
    "adelantos en cta. cte. con acuerdo":           "BNA_ADELANTOS_ACUERDO",
    "descubiertos en cta. cte. previamente solicitado": "BNA_DESCUBIERTO_SOLICITADO",
    "descubiertos en cta. cte. no solicitado previamente (tasa)":
        "BNA_DESCUBIERTO_NO_SOLICITADO",
    "descubiertos en cta. cte. c/garantia hipotecaria":
        "BNA_DESCUBIERTO_HIPOTECARIA",
}

# La pasiva de referencia. El PDF de operaciones trae MUCHOS plazos fijos
# (tradicional, UVA, digital, por tramo de días y por sector); el que se usa
# como "tasa pasiva del Nación" es el plazo fijo tradicional a 30 días.
CONCEPTO_PASIVA = "BNA_PLAZO_FIJO_30D"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def _pct(s: str):
    try:
        return float(s.replace(".", "").replace(",", ".").replace("%", ""))
    except ValueError:
        return None


def links() -> dict:
    """Los PDF vigentes, descubiertos desde la página. {'cart': url, 'ope': url, …}"""
    r = requests.get(PAGINA, timeout=90, verify=False, headers=UA)
    r.raise_for_status()
    out = {}
    for m in re.finditer(r'([\w/\.]*tasas_(\w+)_(\d+)\.pdf)', r.text):
        ruta, clase, num = m.group(1), m.group(2), int(m.group(3))
        u = ruta if ruta.startswith("http") else BASE + "/" + ruta.lstrip("/")
        # si hubiera más de uno de la misma clase, gana el correlativo más alto
        if clase not in out or out[clase][0] < num:
            out[clase] = (num, u)
    if not out:
        raise RuntimeError(
            "el BNA no devolvió ningún PDF de tasas en %s — cambió la página" % PAGINA)
    return {k: v[1] for k, v in out.items()}


def _filas(pdf_bytes: bytes) -> list[tuple]:
    """(concepto, tna, tea, tem, vigencia) leyendo por coordenada vertical."""
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextContainer

    por_y: dict[int, list] = {}
    for pag in extract_pages(io.BytesIO(pdf_bytes)):
        for el in pag:
            if not isinstance(el, LTTextContainer):
                continue
            for ln in el:
                txt = (getattr(ln, "get_text", lambda: "")() or "").strip()
                if txt:
                    por_y.setdefault(round(ln.y0), []).append((round(ln.x0), txt))

    # ⚠ Se juntan las y's que difieren en ≤2 pt: es una sola fila que el
    # extractor partió porque el concepto es más alto que sus números.
    ys = sorted(por_y, reverse=True)
    grupos, actual = [], []
    for y in ys:
        if actual and abs(actual[-1] - y) <= 2:
            actual.append(y)
        else:
            if actual:
                grupos.append(actual)
            actual = [y]
    if actual:
        grupos.append(actual)

    filas = []
    for g in grupos:
        celdas = sorted(c for y in g for c in por_y[y])
        textos = [t for _, t in celdas]
        concepto = textos[0] if textos else ""
        pcts = [t for t in textos if t.endswith("%")]
        vig = next((t for t in textos if re.fullmatch(r"\d{2}-\d{2}-\d{2}", t)), None)
        if concepto.endswith("%") or len(pcts) < 1:
            continue
        filas.append((concepto,
                      _pct(pcts[0]) if len(pcts) > 0 else None,
                      _pct(pcts[1]) if len(pcts) > 1 else None,
                      _pct(pcts[2]) if len(pcts) > 2 else None,
                      vig))
    return filas


def _bajar(url: str) -> bytes:
    r = requests.get(url, timeout=120, verify=False, headers=UA)
    r.raise_for_status()
    if r.content[:4] != b"%PDF":
        raise RuntimeError("lo que bajó de %s no es un PDF" % url)
    return r.content


def fetch_activas() -> list[dict]:
    """Cartera general, adelantos y descubiertos. Una foto, con su vigencia."""
    u = links().get("cart")
    if not u:
        raise RuntimeError("no apareció el PDF de tasas de cartera (tasas_cart_*)")
    out = []
    for concepto, tna, tea, tem, vig in _filas(_bajar(u)):
        serie = CONCEPTOS.get(_norm(concepto))
        if serie and tna is not None:
            out.append({"serie": serie, "concepto": concepto, "tna": tna,
                        "tea": tea, "tem": tem, "vigencia": vig, "fuente": u})
    return out


# ⚠ NO es la página de Plazo Fijo: es el ENDPOINT que esa página llama.
# La tabla en pesos NO viene en el HTML de /Personas/PlazoFijoSucursal — esa la
# arma JavaScript llamando acá (las de dólares y UVA sí vienen en el HTML, que
# es justo lo que hace el error difícil de ver: bajar la página con requests
# devuelve tablas, pero las equivocadas).
PAGINA_PLAZO_FIJO = "https://www.bna.com.ar/Home/GetTasasVigentes"
PAGINA_PLAZO_FIJO_HUMANA = "https://www.bna.com.ar/Personas/PlazoFijoSucursal"

# Las tres columnas de la tabla de plazo fijo en pesos. Son CANALES distintos
# del mismo producto y pagan distinto: al 11/09/2026, a 30 días, sucursal paga
# 15,50 % y Nación Empresa 24 paga 19,50 %. Cuál es "la tasa pasiva del Nación"
# depende de para qué se la use, así que se guardan las tres y que elija quien
# calcula.
CANALES_PASIVA = {
    0: ("BNA_PF30_SUCURSAL", "Plazo fijo tradicional, sucursal"),
    1: ("BNA_PF30_ELECTRONICO", "Plazo fijo, canal electrónico personas humanas"),
    2: ("BNA_PF30_EMPRESAS", "Plazo fijo, canal electrónico Nación Empresa 24 / BNA+"),
}


def fetch_pasiva() -> list[dict]:
    """Plazo fijo en pesos a 30 días — de «Plazo Fijo → Consulta de Tasas Vigentes».

    ⚠⚠ ESTO NO SALE DEL PDF DE OPERACIONES, Y NO ES CAPRICHO. En ese PDF hay
    ocho tablas de plazo fijo y en todas el renglón se llama «30 a 59 días»,
    con columnas que no siempre son las mismas; el primer intento devolvió la
    TEA en el lugar de la TEM sin que nada lo delatara. Esta página, en cambio,
    trae UNA tabla con encabezados propios, los tres canales rotulados y la
    moneda en el título. Es la fuente que corresponde (Juan, 2026-09-11:
    *«de la web del banco → Plazo Fijo → Consulta de Tasas Vigentes»*).

    ⚠ SE PIDE EL ENDPOINT, NO LA PÁGINA. `/Home/GetTasasVigentes` devuelve esta
    tabla sola, en 4 KB de HTML, sin necesidad de navegador. Bajar la página de
    Plazo Fijo con `requests` devuelve las tablas de dólares y UVA pero NO la de
    pesos, que la inserta JavaScript — un scraper que mire "la primera tabla"
    ahí termina informando 0,75 % como tasa pasiva en pesos.

    ⚠ LA DE DÓLARES ESTÁ EN LA MISMA PÁGINA y tiene los mismos rótulos de
    plazo. Por eso se exige que el título diga EN PESOS: agarrar la de dólares
    daría 0,75 % — absurdo como tasa en pesos, pero perfectamente parseable.
    """
    from bs4 import BeautifulSoup

    r = requests.get(PAGINA_PLAZO_FIJO, timeout=90, verify=False, headers=UA)
    r.raise_for_status()
    sopa = BeautifulSoup(r.text, "html.parser")

    for tabla in sopa.find_all("table"):
        filas = [[_norm(c.get_text(" ")) for c in tr.find_all(["td", "th"])]
                 for tr in tabla.find_all("tr")]
        titulo = " ".join(filas[0]) if filas else ""
        if "plazo fijo" not in titulo or "en pesos" not in titulo:
            continue
        for f in filas:
            if not f or not re.match(r"^de 30 a \d+", f[0]):
                continue
            pcts = [_pct(c) for c in f[1:] if c.endswith("%")]
            out = []
            for i, (serie, nombre) in CANALES_PASIVA.items():
                tna, tea = pcts[2 * i:2 * i + 2] or (None, None)
                if tna is not None:
                    out.append({"serie": serie, "concepto": nombre,
                                "plazo": f[0], "tna": tna, "tea": tea,
                                "tem": None, "vigencia": None,
                                "fuente": PAGINA_PLAZO_FIJO})
            if out:
                return out
    return [{"serie": "BNA_PF30_SUCURSAL", "error":
             "no se encontró la tabla de plazo fijo EN PESOS a 30 días en %s — "
             "revisar la página antes de confiar en un número"
             % PAGINA_PLAZO_FIJO}]


def _slug(txt: str, largo: int = 26) -> str:
    t = _norm(txt)
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
    return t[:largo].strip("_").upper()


# ⚠⚠ EL NOMBRE DE LA SERIE TIENE QUE LLEVAR LA MONEDA, Y NO ES COSMÉTICO.
# Los títulos «DEPÓSITOS A PLAZO FIJO EN PESOS SECTOR PRIVADO» y «… EN DÓLARES
# SECTOR PRIVADO» comparten los primeros 22 caracteres. Truncando el título se
# generaba el MISMO nombre para los dos, y como el scraper saltea los nombres
# repetidos, la tabla en dólares tapaba a la de pesos sin error ni aviso: la
# tasa pasiva a 30 días pasaba de 15,50 % a 0,75 % y nada lo delataba.
# Por eso la moneda se extrae aparte y va primero en el nombre.
MONEDAS = (("uva", "UVA"), ("dolar", "USD"), ("peso", "ARS"))


def _nombre_serie(producto: str, canal: str, plazo: str) -> str:
    p = _norm(producto)
    moneda = next((tag for clave, tag in MONEDAS if clave in p), "SIN_MONEDA")
    # qué producto, más allá de la moneda (tradicional, precancelable, jurídicas…)
    tipo = "PRECANC" if "precancelable" in p else (
        "SUBPER" if "subperiodo" in p else (
            "JURIDICAS" if "juridica" in p else "TRAD"))
    return "BNA_PF_%s_%s_%s_%s" % (moneda, tipo, _slug(canal, 12), _slug(plazo, 10))


def _tabla_tasas(tabla) -> list[dict]:
    """Una tabla de plazo fijo del BNA -> un registro por (canal, plazo, tasa).

    ⚠ LA CABECERA TIENE DOS PISOS Y HAY QUE CRUZARLOS. Arriba van los CANALES
    ("Tasas por Sucursal", "Canal electrónico…") y abajo, debajo de cada uno,
    su par TNA/TEA. Un canal ocupa dos columnas; leer solo la fila de TNA/TEA
    pierde de qué canal es cada par, y ahí es donde 15,50 (sucursal) y 19,50
    (empresas) se vuelven indistinguibles.
    """
    filas = [[c.get_text(" ").strip() for c in tr.find_all(["td", "th"])]
             for tr in tabla.find_all("tr")]
    filas = [f for f in filas if any(x.strip() for x in f)]
    if not filas:
        return []

    producto = " ".join(filas[0]).strip()
    # la fila de medidas es la que tiene TNA
    i_med = next((i for i, f in enumerate(filas)
                  if any(_norm(c) in ("tna", "t.n.a.") for c in f)), None)
    if i_med is None:
        return []
    medidas = [_norm(c).replace(".", "") for c in filas[i_med]]

    # los canales están en alguna fila anterior; si no hay, es una sola columna
    canales = []
    for f in filas[:i_med]:
        if len([c for c in f if c.strip()]) > 1 and not any(
                re.match(r"^m.nimo", _norm(c)) for c in f):
            canales = [c.strip() for c in f if c.strip()]
    if not canales:
        canales = ["unico"]

    # cada canal ocupa tantas columnas como medidas haya por canal
    med_datos = [m for m in medidas if m in ("tna", "tea", "tem")]
    por_canal = max(1, len(med_datos) // max(1, len(canales)))

    out = []
    for f in filas[i_med + 1:]:
        if not f or not re.match(r"^(de |hasta )?\d", _norm(f[0])):
            continue
        plazo = f[0].strip()
        vals = [c for c in f[1:] if c.strip().endswith("%")]
        for k, canal in enumerate(canales):
            trozo = vals[k * por_canal:(k + 1) * por_canal]
            if not trozo:
                continue
            reg = {"producto": producto, "canal": canal, "plazo": plazo,
                   "fuente": "BNA plazo fijo"}
            for j, v in enumerate(trozo):
                nombre = med_datos[j] if j < len(med_datos) else "tna"
                reg[nombre] = _pct(v)
            if reg.get("tna") is not None:
                reg["serie"] = _nombre_serie(producto, canal, plazo)
                out.append(reg)
    return out


def fetch_plazos_fijos() -> list[dict]:
    """TODOS los plazos fijos publicados: pesos, dólares y UVA, los tres canales.

    ⚠ SON DOS FUENTES Y HAY QUE PEDIR LAS DOS. La de pesos sale del endpoint
    `/Home/GetTasasVigentes`; las de dólares y UVA vienen en el HTML de la
    página. Pedir una sola deja afuera la mitad sin que nada falle.
    """
    from bs4 import BeautifulSoup
    out, vistas = [], set()
    for u in (PAGINA_PLAZO_FIJO, PAGINA_PLAZO_FIJO_HUMANA):
        try:
            r = requests.get(u, timeout=90, verify=False, headers=UA)
            r.raise_for_status()
        except Exception:
            continue
        for tabla in BeautifulSoup(r.text, "html.parser").find_all("table"):
            for reg in _tabla_tasas(tabla):
                if reg["serie"] in vistas:      # la de pesos aparece en las dos
                    continue
                vistas.add(reg["serie"])
                out.append({**reg, "origen": u})
    return out


def fetch_todas() -> list[dict]:
    """La foto completa del día: activas + pasiva, con la fecha del relevamiento.

    ⚠ La fecha es la del RELEVAMIENTO, no la de vigencia. Son dos cosas: la
    vigencia dice desde cuándo rige esa tasa (y se repite días entre cambios);
    la del relevamiento es la que arma la serie diaria. Se guardan las dos.
    """
    hoy = dt.date.today().isoformat()
    filas = []
    for f in fetch_activas() + fetch_plazos_fijos():
        filas.append({"FECHA": hoy, **f})
    return filas


if __name__ == "__main__":
    for f in fetch_todas():
        print("%-32s %-58s TNA %7.2f  TEM %-7s  vig %s"
              % (f["serie"], f["concepto"][:58], f["tna"],
                 f["tem"], f["vigencia"]))
