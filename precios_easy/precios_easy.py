# -*- coding: utf-8 -*-
"""Relevamiento de catálogo y precios públicos de Easy Argentina → CSV en Drive.

Rubros: Sanitarios, Plomería (incluye Distribución de agua), Electricidad y
Pisos y revestimientos. Ubicación: Resistencia, Chaco, CPA H3506.

De dónde sale cada dato (todo es lo que la propia página de Easy consulta;
`robots.txt` sólo prohíbe /admin, /account, `?map=category`, `?initialMap=` y
`/p?idsku=`, y no se toca ninguno):

    ubicación    /api/checkout/pub/postal-code/ARG/3506   → ciudad y provincia
    catálogo     /api/io/_v/api/intelligent-search/product_search/<categoría>
    filtros      /api/io/_v/api/intelligent-search/facets/<categoría>
                 (devuelve TODAS las opciones: lo que la pantalla esconde
                 detrás de «Mostrar más» viene completo)
    precio       /api/checkout/pub/orderForms/simulation con CP 3506
                 (el mismo cálculo que hace el carrito para Resistencia)

⚠ IVA. Easy publica en cada ficha `price_wo_taxes` («precio sin impuestos
nacionales»). Eso NO es por sí mismo «sin IVA»: puede llevar internos, o estar
desactualizado. Se acepta sólo si precio / price_wo_taxes da EXACTAMENTE una
alícuota legal de IVA (21 %, 10,5 % o 27 %) al centavo; entonces la inclusión y
la alícuota quedan verificadas y los importes se guardan divididos por
(1 + alícuota). Si no cierra, el precio queda PENDIENTE y no se escribe.

Corre solo, sin login ni navegador. Drive por `SIBRA_DRIVE` (o `EASY_DRIVE_DIR`).
El cronograma vive en el panel 8400 (`jobs_cronograma`, job `precios_easy`,
cada 10 días).

    python precios_easy.py            # corrida completa
    python precios_easy.py --seco     # releva y valida, no escribe en Drive
"""
import argparse
import csv
import io
import json
import os
import re
import shutil
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── Configuración ────────────────────────────────────────────────────────────
BASE = "https://www.easy.com.ar"
UA = "Mozilla/5.0 (compatible; relevamiento-precios-easy/1.0)"
CPA = "H3506"              # lo que se guarda en CODIGO_POSTAL
CP_EASY = "3506"           # lo que acepta Easy (4 dígitos; con letra no ubica)
CIUDAD, PROVINCIA = "Resistencia", "Chaco"
PAUSA = 0.4                # segundos entre pedidos: no apurar al sitio
POR_PAGINA = 50
TOPE_BUSQUEDA = 2500       # la búsqueda no pagina más allá de 50 páginas
ALICUOTAS = (Decimal("0.21"), Decimal("0.105"), Decimal("0.27"))

ALCANCE = [  # (rubro pedido, ruta de la categoría en Easy)
    # 2026-10-12: Juan pidió TODO el catálogo de Easy (antes: sólo 4 rubros). Son las 17 categorías de primer nivel.
    ("Baños y Cocinas", "/banos-y-cocinas"),
    ("Electrodomésticos", "/electrodomesticos"),
    ("Muebles", "/muebles"),
    ("Organización y Limpieza", "/organizacion-y-limpieza"),
    ("Textil, Bazar y Deco", "/textil-bazar-y-deco"),
    ("Iluminación", "/iluminacion"),
    ("Jardín y Aire Libre", "/jardin-y-aire-libre"),
    ("Automotor", "/automotor"),
    ("Pisos y revestimientos", "/pisos-y-revestimientos"),
    ("Pinturas", "/pinturas"),
    ("Aberturas", "/aberturas"),
    ("Construcción y Maderas", "/construccion-y-maderas"),
    ("Plomería", "/plomeria"),
    ("Electricidad", "/electricidad"),
    ("Herramientas", "/herramientas"),
    ("Ferretería", "/ferreteria"),
    ("Soluciones Modulares", "/soluciones-modulares"),
]
# Especificaciones internas de Easy: no son clasificaciones del producto.
# `price_wo_taxes` además es un importe que todavía no se validó.
SPEC_INTERNAS = {"price_wo_taxes", "sellerid"}

PADRINO_AGUA_ADUCT = "Sí - padrino de «Agua Aduct»"
SIN_PADRINO = "Pendiente de definir"


def _drive_dir():
    if os.environ.get("EASY_DRIVE_DIR"):
        return Path(os.environ["EASY_DRIVE_DIR"])
    raiz = os.environ.get("SIBRA_DRIVE") or (r"H:\My Drive" if os.name == "nt" else "")
    return Path(raiz) / "Precios Easy" if raiz else None


def _state_dir():
    if os.environ.get("EASY_STATE_DIR"):
        return Path(os.environ["EASY_STATE_DIR"])
    if os.name == "nt":
        return Path(r"C:\SIBRA\precios_easy")
    return Path.home() / ".local" / "state" / "precios_easy"


ARCH = {
    "insumos": "Precios Easy - Insumos.csv",
    "precios": f"Precios Easy - Precios {CPA}.csv",
    "historico": f"Precios Easy - Histórico Padrinos {CPA}.csv",
    "promos": f"Precios Easy - Promociones {CPA}.csv",
    "clasif": f"Precios Easy - Clasificaciones {CPA}.csv",
    "filtros": f"Precios Easy - Filtros {CPA}.csv",
    "control": "Precios Easy - Control.csv",
}
COLS = {
    "insumos": "ID_INSUMO,CODIGO_EASY,DESCRIPCION,MARCA,RUBRO,SUBRUBRO,CATEGORIA,SUBCATEGORIA,"
               "ATRIBUTOS_CLAVE,UNIDAD_PRECIO,CONTENIDO_UNIDAD,UNIDAD_CONTENIDO,SKU,GTIN_EAN,"
               "URL_EASY,ES_PADRINO,ESTADO,OBSERVACIONES",
    "precios": "FECHA,ID_INSUMO,CODIGO_POSTAL,PRECIO_SIN_IVA",
    "historico": "FECHA_DESDE,FECHA_ULTIMA_REVISION,ID_INSUMO,CODIGO_POSTAL,PRECIO_SIN_IVA",
    "promos": "FECHA_DETECCION,FECHA_ULTIMA_REVISION,CODIGO_POSTAL,ID_INSUMO,CODIGO_EASY,"
              "DESCRIPCION,PRECIO_LISTA_SIN_IVA,PRECIO_PROMOCIONAL_SIN_IVA,DESCUENTO_PCT,"
              "VIGENCIA,ESTADO_PROMOCION,URL_EASY",
    "clasif": "FECHA_ULTIMA_REVISION,CODIGO_POSTAL,ID_INSUMO,CODIGO_EASY,RUBRO,SUBRUBRO,"
              "CATEGORIA,SUBCATEGORIA,CLASIFICACION,VALOR,ORIGEN,URL_EASY",
    "filtros": "FECHA_ULTIMA_REVISION,CODIGO_POSTAL,RUBRO,SUBRUBRO,CATEGORIA,SUBCATEGORIA,"
               "FILTRO,OPCION,CANTIDAD_RESULTADOS,URL_CATEGORIA",
    "control": "SECCION,CLAVE,VALOR",
}
COLS = {k: v.split(",") for k, v in COLS.items()}
MONETARIAS = {"precios": ["PRECIO_SIN_IVA"], "historico": ["PRECIO_SIN_IVA"],
              "promos": ["PRECIO_LISTA_SIN_IVA", "PRECIO_PROMOCIONAL_SIN_IVA"]}
# Campos del maestro que pueden haber sido asignados a mano: el relevamiento
# sólo los llena si están vacíos, nunca los pisa.
CAMPOS_MANUALES = ["DESCRIPCION", "MARCA", "RUBRO", "SUBRUBRO", "CATEGORIA", "SUBCATEGORIA",
                   "ATRIBUTOS_CLAVE", "UNIDAD_PRECIO", "CONTENIDO_UNIDAD", "UNIDAD_CONTENIDO",
                   "SKU", "GTIN_EAN", "URL_EASY", "ES_PADRINO"]
AUTO = "[auto] "


# ── Log ──────────────────────────────────────────────────────────────────────
class Log:
    def __init__(self, path):
        self.f = open(path, "a", encoding="utf-8") if path else None

    def __call__(self, *a):
        linea = f"{datetime.now():%H:%M:%S} " + " ".join(str(x) for x in a)
        print(linea, flush=True)
        if self.f:
            self.f.write(linea + "\n")
            self.f.flush()


log = Log(None)


# ── HTTP ─────────────────────────────────────────────────────────────────────
class Bloqueado(Exception):
    """El sitio dijo que no (403/429/CAPTCHA). No se insiste ni se esquiva."""


_n_pedidos = 0


def pedir(url, cuerpo=None, intentos=3):
    global _n_pedidos
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    for i in range(intentos):
        time.sleep(PAUSA)
        _n_pedidos += 1
        req = urllib.request.Request(url, data=datos, headers={
            "User-Agent": UA, "Accept": "application/json",
            **({"Content-Type": "application/json"} if datos else {})})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                txt = r.read().decode("utf-8")
            if txt.lstrip().startswith("<"):
                raise Bloqueado(f"devolvió HTML en vez de datos (¿desafío/CAPTCHA?): {url}")
            return json.loads(txt)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                raise Bloqueado(f"HTTP {e.code} en {url}")
            if i == intentos - 1:
                raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if i == intentos - 1:
                raise
        time.sleep(3 * (i + 1))


def _q(**kw):
    return urllib.parse.urlencode(kw)


# ── Montos ───────────────────────────────────────────────────────────────────
def D(x):
    return Decimal(str(x))


def neto(bruto, alic):
    return (D(bruto) / (1 + alic)).quantize(Decimal("0.01"), ROUND_HALF_UP)


def fmt(d):
    return "" if d is None else f"{d:.2f}"


def verificar_iva(sin_imp, lista, venta):
    """Devuelve (alícuota, motivo). Alícuota None = no verificable."""
    if sin_imp is None:
        return None, "Easy no publica el precio sin impuestos nacionales"
    try:
        w = D(sin_imp)
    except Exception:
        return None, f"precio sin impuestos ilegible ({sin_imp!r})"
    if w <= 0:
        return None, "precio sin impuestos en cero"
    for a in ALICUOTAS:
        for bruto in (lista, venta):
            if bruto and abs(w * (1 + a) - D(bruto)) <= max(Decimal("0.02"), D(bruto) * Decimal("0.00005")):
                return a, ""
    return None, ("el precio sin impuestos nacionales no cierra con ninguna alícuota de IVA "
                  "(21/10,5/27 %): puede estar desactualizado o incluir otros impuestos")


# ── CSV ──────────────────────────────────────────────────────────────────────
def leer_csv(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def csv_texto(cols, filas):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in filas:
        w.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in cols})
    return buf.getvalue()


def escribir_atomico(path, texto):
    """Escribe al lado y reemplaza: si algo corta a mitad, el archivo anterior
    queda entero. Después relee y compara."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        f.write(texto)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    with open(path, encoding="utf-8-sig", newline="") as f:
        if f.read() != texto:
            raise IOError(f"la relectura de {path.name} no coincide con lo escrito")


# ── Candado ──────────────────────────────────────────────────────────────────
class Candado:
    VIEJO = 12 * 3600   # una corrida no tarda esto: si el candado es más viejo, quedó colgado

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {datetime.now().isoformat()}".encode())
                os.close(fd)
                return self
            except FileExistsError:
                if self._abandonado():
                    os.remove(self.path)
                    continue
                raise SystemExit(f"Ya hay una corrida en curso (candado {self.path}). "
                                 "Si no es así, borrá ese archivo y reintentá.")
        raise SystemExit("no pude tomar el candado")

    def _abandonado(self):
        try:
            pid = int(self.path.read_text().split()[0])
        except Exception:
            return True
        if os.name != "nt":
            try:
                os.kill(pid, 0)
                return False
            except ProcessLookupError:
                return True
            except PermissionError:
                return False
        return time.time() - self.path.stat().st_mtime > self.VIEJO

    def __exit__(self, *a):
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass


# ── Relevamiento ─────────────────────────────────────────────────────────────
class Corrida:
    def __init__(self):
        self.hoy = datetime.now().strftime("%Y-%m-%d")
        self.problemas = []          # (qué, motivo) — lo que no se cubrió
        self.cp_confirmado = False
        self.cp = ""
        self.productos = {}          # productId → dict normalizado
        self.por_rubro = {}          # rubro → {"paginas", "productos": set()}
        self.nodos = []              # categorías del alcance
        self.facetas = {}            # url_categoria → (nodo, [filas]) sólo las que se leyeron bien
        self.stats_nodo = {}         # url → dict
        self.gross_vistos = set()    # todos los importes CON IVA vistos: no pueden aparecer escritos
        self.netos_calculados = set()

    def problema(self, que, motivo):
        self.problemas.append((que, motivo))
        log("⚠", que, "—", motivo)

    # 1 · ubicación
    def ubicar(self):
        try:
            d = pedir(f"{BASE}/api/checkout/pub/postal-code/ARG/{CP_EASY}")
            ok = (d.get("city") or "").strip().lower() == CIUDAD.lower() and \
                 (d.get("state") or "").strip().lower() == PROVINCIA.lower()
            r = pedir(f"{BASE}/api/checkout/pub/regions?{_q(country='ARG', postalCode=CP_EASY)}")
            sellers = [s["id"] for reg in r for s in reg.get("sellers", [])]
            tienda = [s for s in sellers if "resistencia" in s.lower()]
            self.cp_confirmado = ok
            self.cp = CPA if ok else ""
            self.ubicacion_txt = (f"Easy ubica el CP {CP_EASY} en {d.get('city')}, {d.get('state')}; "
                                  f"tienda de la región: {', '.join(tienda) or 'ninguna'}. "
                                  f"El CPA {CPA} con letra Easy no lo reconoce: se consulta con {CP_EASY}.")
            if not ok:
                self.problema("Ubicación", f"Easy no confirmó Resistencia, Chaco para {CP_EASY} "
                                           f"(devolvió {d.get('city')!r}, {d.get('state')!r}); CODIGO_POSTAL vacío")
            log("ubicación:", self.ubicacion_txt)
        except Exception as e:
            self.cp_confirmado, self.cp = False, ""
            self.ubicacion_txt = f"no se pudo consultar: {e}"
            self.problema("Ubicación", f"no se pudo confirmar: {e}; CODIGO_POSTAL vacío")

    # 2 · árbol
    def arbol(self):
        t = pedir(f"{BASE}/api/catalog_system/pub/category/tree/4")

        def camino(nodos, pref):
            for n in nodos:
                ruta = urllib.parse.urlparse(n["url"]).path
                yield n, pref + [n["name"]], ruta
                yield from camino(n.get("children", []), pref + [n["name"]])
        todos = list(camino(t, []))
        for rubro, ruta in ALCANCE:
            raiz = [x for x in todos if x[2] == ruta]
            if not raiz:
                self.problema(f"Rubro {rubro}", f"la categoría {ruta} ya no existe en el árbol de Easy")
                continue
            for n, nombres, r in todos:
                if r == ruta or r.startswith(ruta + "/"):
                    self.nodos.append({"rubro": rubro, "id": n["id"], "nombres": nombres, "ruta": r,
                                       "hijos": [urllib.parse.urlparse(c["url"]).path for c in n.get("children", [])]})
        log(f"árbol: {len(self.nodos)} categorías en el alcance")

    @staticmethod
    def _facet_path(ruta):
        partes = [p for p in ruta.split("/") if p]
        return "/".join(f"category-{i + 1}/{urllib.parse.quote(p)}" for i, p in enumerate(partes))

    @staticmethod
    def _niveles(nombres):
        n = list(nombres) + ["", "", "", ""]
        return {"RUBRO": n[0], "SUBRUBRO": n[1], "CATEGORIA": n[2], "SUBCATEGORIA": n[3]}

    # 3 · filtros
    def filtros(self):
        for nodo in self.nodos:
            url = BASE + nodo["ruta"]
            try:
                d = pedir(f"{BASE}/api/io/_v/api/intelligent-search/facets/{self._facet_path(nodo['ruta'])}?"
                          + _q(locale="es-AR", hideUnavailableItems="false"))
            except Exception as e:
                self.problema(f"Filtros {nodo['ruta']}", str(e))
                continue
            facetas = d.get("facets", [])
            nombres = [f.get("name") for f in facetas]
            filas, incompletos, excluidos = [], [], []
            for f in facetas:
                if f.get("type") == "PRICERANGE":
                    excluidos.append(f.get("name"))   # rangos en pesos CON IVA: no se guardan
                    continue
                nom = f.get("name") or ""
                if nombres.count(nom) > 1:          # Easy repite «Marca» con dos fuentes
                    nom = f"{nom} [{(f.get('values') or [{}])[0].get('key', '')}]"
                vals = f.get("values", [])
                if f.get("quantity") is not None and len(vals) < int(f["quantity"]):
                    incompletos.append(f"{nom}: {len(vals)} de {f['quantity']}")
                for v in vals:
                    filas.append({"FECHA_ULTIMA_REVISION": self.hoy, "CODIGO_POSTAL": self.cp,
                                  **self._niveles(nodo["nombres"]), "FILTRO": nom,
                                  "OPCION": v.get("name") or v.get("value") or "",
                                  "CANTIDAD_RESULTADOS": v.get("quantity", ""), "URL_CATEGORIA": url})
            if incompletos:
                self.problema(f"Filtros {nodo['ruta']}", "opciones incompletas: " + "; ".join(incompletos))
            self.facetas[url] = (nodo, filas)
            st = self.stats_nodo.setdefault(url, {})
            st.update(filtros=len({r["FILTRO"] for r in filas}), opciones=len(filas),
                      filtros_excluidos=", ".join(excluidos))
        log(f"filtros: {len(self.facetas)}/{len(self.nodos)} categorías leídas")

    # 4 · productos
    def _buscar_nodo(self, nodo, porruta):
        """Pagina una categoría entera. Si pasa el tope de la búsqueda, baja a las hijas."""
        fp = self._facet_path(nodo["ruta"])
        base_url = f"{BASE}/api/io/_v/api/intelligent-search/product_search/{fp}?"
        url_cat = BASE + nodo["ruta"]
        st = self.stats_nodo.setdefault(url_cat, {})
        primera = pedir(base_url + _q(count=POR_PAGINA, page=1, locale="es-AR", hideUnavailableItems="false"))
        total = int(primera.get("recordsFiltered") or 0)
        st["productos_easy"] = total
        if total > TOPE_BUSQUEDA:
            if not nodo["hijos"]:
                self.problema(f"Productos {nodo['ruta']}", f"{total} productos y la búsqueda no pasa de "
                                                            f"{TOPE_BUSQUEDA}; sin subcategorías para partir")
            got = set()
            for h in nodo["hijos"]:
                got |= self._buscar_nodo(porruta[h], porruta)
            if len(got) < total:
                self.problema(f"Productos {nodo['ruta']}", f"{total - len(got)} productos sin subcategoría "
                                                            f"no alcanzables (tope de {TOPE_BUSQUEDA} de la búsqueda)")
            st["productos_cubiertos"] = len(got)
            return got
        got, paginas, d, page = set(), 0, primera, 1
        while True:
            paginas += 1
            for p in d.get("products", []):
                got.add(p["productId"])
                self._tomar(p, nodo["rubro"])
            if page * POR_PAGINA >= total or not d.get("products"):
                break
            page += 1
            d = pedir(base_url + _q(count=POR_PAGINA, page=page, locale="es-AR", hideUnavailableItems="false"))
        r = self.por_rubro.setdefault(nodo["rubro"], {"paginas": 0, "productos": set()})
        r["paginas"] += paginas
        r["productos"] |= got
        st["productos_cubiertos"] = len(got)
        st["paginas"] = paginas
        if len(got) < total:
            self.problema(f"Productos {nodo['ruta']}", f"Easy informa {total} y se obtuvieron {len(got)}")
        return got

    def catalogo(self):
        porruta = {n["ruta"]: n for n in self.nodos}
        for rubro, ruta in ALCANCE:
            if ruta not in porruta:
                continue
            try:
                got = self._buscar_nodo(porruta[ruta], porruta)
                log(f"catálogo {rubro}: {len(got)} productos")
            except Exception as e:
                self.problema(f"Productos {ruta}", f"corte en la paginación: {e}")

    def _tomar(self, p, rubro, origen="búsqueda"):
        pid = p["productId"]
        if pid in self.productos:
            self.productos[pid]["rubros"].add(rubro)
            return
        items = p.get("items") or []
        it = items[0] if items else {}
        sellers = it.get("sellers") or []
        cats = sorted(p.get("categories") or [], key=len)
        nombres = [c for c in (cats[-1] if cats else "").split("/") if c]
        props = [x for x in (p.get("properties") or [])]
        sin_imp = next((x["values"][0] for x in props if x.get("name") == "price_wo_taxes" and x.get("values")), None)
        specs = []
        for g in p.get("specificationGroups") or []:
            if g.get("name") == "allSpecifications":
                continue
            for s in g.get("specifications") or []:
                n = s.get("name") or ""
                if n.lower() in SPEC_INTERNAS or "price" in n.lower() or "precio" in n.lower():
                    continue
                for v in s.get("values") or []:
                    specs.append((n, str(v).strip(), f"Ficha de producto · {g.get('name')}"))
        for s in p.get("skuSpecifications") or []:
            n = (s.get("field") or {}).get("name") or ""
            for v in s.get("values") or []:
                specs.append((n, str(v.get("name", "")).strip(), "Ficha de producto · variante"))
        if p.get("brand"):
            specs.append(("Marca", p["brand"], "Tarjeta de producto"))
        # La referencia pública es la del producto; si Easy la deja vacía, la
        # misma referencia viene en el ítem (RefId). No se inventa otra.
        ref = (p.get("productReference") or "").strip() or next(
            (str(r.get("Value") or "").strip() for r in it.get("referenceId") or []
             if r.get("Key") == "RefId"), "")
        link = p.get("linkText") or ""
        self.productos[pid] = {
            "pid": pid, "ref": ref, "nombre": (p.get("productName") or "").strip(),
            "marca": p.get("brand") or "", "niveles": self._niveles(nombres),
            "item": it.get("itemId"), "seller": (sellers[0].get("sellerId") if sellers else "1"),
            "ean": (it.get("ean") or "").strip(), "unidad": it.get("measurementUnit") or "",
            "mult": it.get("unitMultiplier"), "n_items": len(items),
            "url": f"{BASE}/{urllib.parse.quote(link)}/p" if link else "",
            "sin_imp": sin_imp, "specs": specs, "rubros": {rubro}, "origen": origen,
        }

    def maestro_fuera_de_alcance(self, maestro):
        """Los insumos que ya están en el maestro y no aparecieron en los cuatro
        rubros (p. ej. cementos): se buscan uno por uno para no dejarlos sin revisar."""
        vistos = {p["ref"] for p in self.productos.values()}
        for m in maestro:
            ref = (m.get("CODIGO_EASY") or "").strip()
            if not ref or ref in vistos:
                continue
            try:
                r = pedir(f"{BASE}/api/catalog_system/pub/products/search?" + _q(fq=f"alternateIds_RefId:{ref}"))
            except Exception as e:
                self.problema(f"Insumo {ref}", f"no se pudo consultar: {e}")
                continue
            if not r:
                continue
            self._tomar(self._de_legacy(r[0]), "Fuera de los cuatro rubros (ya estaba en el maestro)", "ficha")

    @staticmethod
    def _de_legacy(p):
        """El buscador viejo trae las especificaciones como claves sueltas."""
        props = [{"name": n, "values": p.get(n) or []} for n in p.get("allSpecifications") or []]
        grupos = [{"name": g, "specifications": [{"name": n, "values": p.get(n) or []} for n in p.get(g) or []]}
                  for g in p.get("allSpecificationsGroups") or []]
        return {**p, "properties": props, "specificationGroups": grupos, "skuSpecifications": []}

    # 5 · precios en Resistencia
    def precios(self):
        prods = [p for p in self.productos.values() if p["item"]]
        for i in range(0, len(prods), 50):
            lote = prods[i:i + 50]
            cuerpo = {"items": [{"id": p["item"], "quantity": 1, "seller": p["seller"]} for p in lote],
                      "country": "ARG", "postalCode": CP_EASY}
            try:
                d = pedir(f"{BASE}/api/checkout/pub/orderForms/simulation?sc=1", cuerpo)
            except Exception as e:
                self.problema(f"Precios lote {i // 50 + 1}", str(e))
                continue
            for it in d.get("items", []):
                idx = it.get("requestIndex")
                if idx is None or idx >= len(lote):
                    continue
                p = lote[idx]
                p["sim"] = {"lista": D(it.get("listPrice") or 0) / 100,
                            "venta": D(it.get("sellingPrice") or it.get("price") or 0) / 100,
                            "disp": it.get("availability")}
        # El carrito de UN producto dice qué entregas hay para el CP: si aparece
        # el retiro en la tienda de Resistencia, la ubicación quedó confirmada
        # también del lado del precio.
        # Se prueba con productos disponibles: uno sin stock no ofrece entregas.
        slas = []
        for p in [p for p in prods if (p.get("sim") or {}).get("disp") == "available"][:5]:
            try:
                d = pedir(f"{BASE}/api/checkout/pub/orderForms/simulation?sc=1",
                          {"items": [{"id": p["item"], "quantity": 1, "seller": p["seller"]}],
                           "country": "ARG", "postalCode": CP_EASY})
                slas = sorted({s.get("name") for li in d.get("logisticsInfo", []) for s in li.get("slas", [])})
            except Exception as e:
                self.ubicacion_txt += f" No se pudo leer las entregas del carrito: {e}."
                break
            if slas:
                break
        self.ubicacion_txt += f" Entregas que ofrece el carrito para {CP_EASY}: {', '.join(slas) or 'ninguna'}."
        for p in self.productos.values():
            s = p.get("sim")
            p["alic"], p["pend"] = None, ""
            if not p["ref"]:
                p["pend"] = "sin referencia pública de Easy"
                continue
            if not s or s["venta"] <= 0:
                p["pend"] = "Easy no devolvió precio para el CP 3506"
                continue
            self.gross_vistos |= {f"{s['lista']:.2f}", f"{s['venta']:.2f}"}
            a, motivo = verificar_iva(p["sin_imp"], s["lista"], s["venta"])
            if a is None:
                p["pend"] = motivo
                continue
            p["alic"] = a
            lista = max(s["lista"], s["venta"])
            p["neto_lista"] = neto(lista, a)
            p["neto_venta"] = neto(s["venta"], a)
            p["promo"] = s["venta"] < lista - D("0.005")
            p["desc_pct"] = ((1 - s["venta"] / lista) * 100).quantize(Decimal("0.01"), ROUND_HALF_UP) if p["promo"] else None
            self.netos_calculados |= {fmt(p["neto_lista"]), fmt(p["neto_venta"])}


# ── Fusión con lo que ya hay en Drive ────────────────────────────────────────
def fusionar(c, prev):
    hoy, cp = c.hoy, c.cp
    por_ref = {p["ref"]: p for p in c.productos.values() if p["ref"]}
    R = {"precio_cambios": [], "padrinos_cambio": [], "hist_agregados": 0,
         "promo_nuevas": 0, "promo_modif": 0, "promo_fin": 0, "pendientes": []}

    # Maestro
    insumos, ya = [], set()
    for m in prev["insumos"]:
        ref = (m.get("CODIGO_EASY") or "").strip()
        p = por_ref.get(ref)
        ya.add(ref)
        if p:
            nuevo = _fila_insumo(p)
            # El precio es SIEMPRE por la unidad de venta de Easy. Si el maestro
            # dice otra unidad (p. ej. m² cuando Easy vende la caja), no se pisa
            # lo cargado a mano, pero se avisa: comparar precios así da mal.
            # «bolsa», «rollo» o «caja» contra «un» es lo mismo: una pieza. Sólo
            # importa cuando el maestro dice una MEDIDA (m², m, kg, l).
            u_m = (m.get("UNIDAD_PRECIO") or "").strip()
            medidas = {"m²", "m2", "m", "ml", "kg", "l", "lt"}
            if u_m.lower() in medidas and u_m.lower().replace("²", "2") != nuevo["UNIDAD_PRECIO"].lower().replace("²", "2"):
                R.setdefault("unidad_distinta", []).append(
                    (m.get("ID_INSUMO"), u_m, nuevo["UNIDAD_PRECIO"]))
            for k in CAMPOS_MANUALES:
                if not (m.get(k) or "").strip():
                    m[k] = nuevo[k]
            m["ESTADO"] = nuevo["ESTADO"]
            obs = m.get("OBSERVACIONES") or ""
            if not obs or obs.startswith(AUTO):
                m["OBSERVACIONES"] = nuevo["OBSERVACIONES"]
        elif ref:
            m["ESTADO"] = f"No encontrado en la revisión {hoy}"
        insumos.append(m)
    for p in c.productos.values():
        if p["ref"] and p["ref"] in ya:
            continue
        insumos.append(_fila_insumo(p))
        ya.add(p["ref"])

    # Padrino propuesto: caño de agua Aduct 110 mm × 4 m
    cand = [m for m in insumos if re.search(r"a\w?aduct", (m.get("DESCRIPCION") or "") + " " + (m.get("MARCA") or ""), re.I)
            and re.search(r"\b110\s*mm\b|\b110\b", m.get("DESCRIPCION") or "")
            and re.search(r"\b4\s*(m|mt|mts|metros)\b", m.get("DESCRIPCION") or "", re.I)
            and re.search(r"ca[ñn]o|tubo", m.get("DESCRIPCION") or "", re.I)]
    R["padrino_candidatos"] = [f"{m['ID_INSUMO']} {m['DESCRIPCION']}" for m in cand]
    if len(cand) == 1 and (cand[0].get("ES_PADRINO") or SIN_PADRINO) == SIN_PADRINO:
        cand[0]["ES_PADRINO"] = PADRINO_AGUA_ADUCT
    padrinos = {m["ID_INSUMO"] for m in insumos if (m.get("ES_PADRINO") or "").startswith("Sí")}

    # Precio vigente
    precios = {(r["ID_INSUMO"], r["CODIGO_POSTAL"]): r for r in prev["precios"]}
    for p in c.productos.values():
        idi = f"EASY-{p['ref']}" if p["ref"] else ""
        if not idi:
            continue
        if p.get("alic") is None or not cp:
            antes = precios.get((idi, cp))
            R["pendientes"].append((idi, p["pend"] or "CP sin confirmar", antes["FECHA"] if antes else "nunca"))
            continue
        nuevo = fmt(p["neto_lista"])
        antes = precios.get((idi, cp))
        if antes and antes["PRECIO_SIN_IVA"] != nuevo:
            R["precio_cambios"].append((idi, antes["PRECIO_SIN_IVA"], nuevo))
        precios[(idi, cp)] = {"FECHA": hoy, "ID_INSUMO": idi, "CODIGO_POSTAL": cp, "PRECIO_SIN_IVA": nuevo}

    # Histórico de padrinos
    hist = list(prev["historico"])
    for (idi, pcp), r in precios.items():
        if idi not in padrinos or r["FECHA"] != hoy:
            continue
        abiertos = [h for h in hist if h["ID_INSUMO"] == idi and h["CODIGO_POSTAL"] == pcp]
        ult = max(abiertos, key=lambda h: (h["FECHA_DESDE"], h["FECHA_ULTIMA_REVISION"]), default=None)
        if ult and ult["PRECIO_SIN_IVA"] == r["PRECIO_SIN_IVA"]:
            ult["FECHA_ULTIMA_REVISION"] = hoy
        else:
            if ult:
                R["padrinos_cambio"].append((idi, ult["PRECIO_SIN_IVA"], r["PRECIO_SIN_IVA"]))
            hist.append({"FECHA_DESDE": hoy, "FECHA_ULTIMA_REVISION": hoy, "ID_INSUMO": idi,
                         "CODIGO_POSTAL": pcp, "PRECIO_SIN_IVA": r["PRECIO_SIN_IVA"]})
            R["hist_agregados"] += 1

    # Promociones
    promos = list(prev["promos"])
    for p in c.productos.values():
        if not p["ref"] or not cp or not p.get("sim"):
            continue
        idi = f"EASY-{p['ref']}"
        s = p["sim"]
        lista_b = max(s["lista"], s["venta"])
        hay = s["venta"] < lista_b - D("0.005")
        vig = [x for x in promos if x["ID_INSUMO"] == idi and x["CODIGO_POSTAL"] == cp
               and x["ESTADO_PROMOCION"] == "Vigente"]
        if not hay:
            for x in vig:
                x["ESTADO_PROMOCION"] = "Finalizada"
                R["promo_fin"] += 1
            continue
        pct = ((1 - s["venta"] / lista_b) * 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
        fila = {"FECHA_DETECCION": hoy, "FECHA_ULTIMA_REVISION": hoy, "CODIGO_POSTAL": cp,
                "ID_INSUMO": idi, "CODIGO_EASY": p["ref"], "DESCRIPCION": p["nombre"],
                "PRECIO_LISTA_SIN_IVA": fmt(p.get("neto_lista")) if p.get("alic") else "",
                "PRECIO_PROMOCIONAL_SIN_IVA": fmt(p.get("neto_venta")) if p.get("alic") else "",
                "DESCUENTO_PCT": f"{pct:.2f}", "VIGENCIA": "", "ESTADO_PROMOCION": "Vigente",
                "URL_EASY": p["url"]}
        clave = lambda x: (x["PRECIO_LISTA_SIN_IVA"], x["PRECIO_PROMOCIONAL_SIN_IVA"], x["DESCUENTO_PCT"], x["VIGENCIA"])
        igual = [x for x in vig if clave(x) == clave(fila)]
        if igual:
            igual[0]["FECHA_ULTIMA_REVISION"] = hoy
            continue
        for x in vig:
            x["ESTADO_PROMOCION"] = "Finalizada"
        R["promo_modif" if vig else "promo_nuevas"] += 1
        promos.append(fila)
    R["promo_vigentes"] = sum(1 for x in promos if x["ESTADO_PROMOCION"] == "Vigente")

    # Clasificaciones: las del producto revisado se reemplazan por lo publicado hoy
    revisados = {f"EASY-{p['ref']}" for p in c.productos.values() if p["ref"]}
    clasif = [r for r in prev["clasif"] if r["ID_INSUMO"] not in revisados]
    for p in c.productos.values():
        if not p["ref"]:
            continue
        vistos = set()
        for n, v, o in p["specs"]:
            if (n, v, o) in vistos or not v:
                continue
            vistos.add((n, v, o))
            clasif.append({"FECHA_ULTIMA_REVISION": hoy, "CODIGO_POSTAL": cp, "ID_INSUMO": f"EASY-{p['ref']}",
                           "CODIGO_EASY": p["ref"], **p["niveles"], "CLASIFICACION": n, "VALOR": v,
                           "ORIGEN": o, "URL_EASY": p["url"]})

    # Filtros: las categorías leídas hoy se reemplazan; las que fallaron conservan lo anterior
    leidas = set(c.facetas)
    filtros = [r for r in prev["filtros"] if r["URL_CATEGORIA"] not in leidas]
    previas = {(r["URL_CATEGORIA"], r["FILTRO"], r["OPCION"]) for r in prev["filtros"] if r["URL_CATEGORIA"] in leidas}
    actuales = set()
    for _, filas in c.facetas.values():
        filtros.extend(filas)
        actuales |= {(r["URL_CATEGORIA"], r["FILTRO"], r["OPCION"]) for r in filas}
    R["opciones_bajas"] = sorted(previas - actuales)
    R["opciones_altas"] = len(actuales - previas)

    return {"insumos": insumos, "precios": sorted(precios.values(), key=lambda r: (r["ID_INSUMO"], r["CODIGO_POSTAL"])),
            "historico": hist, "promos": promos, "clasif": clasif, "filtros": filtros}, R


def _fila_insumo(p):
    n = p["niveles"]
    attrs = "; ".join(f"{a}: {v}" for a, v, o in p["specs"] if o.startswith("Ficha"))
    if p.get("alic") is not None:
        obs = f"IVA {p['alic'] * 100:.1f} % verificado contra el precio sin impuestos nacionales de Easy"
    else:
        obs = f"Precio pendiente: {p.get('pend') or 'sin revisar'}"
    if p["n_items"] > 1:
        obs += f"; Easy publica {p['n_items']} variantes, se tomó la primera"
    disp = (p.get("sim") or {}).get("disp")
    return {"ID_INSUMO": f"EASY-{p['ref']}" if p["ref"] else "", "CODIGO_EASY": p["ref"],
            "DESCRIPCION": p["nombre"], "MARCA": p["marca"], **n, "ATRIBUTOS_CLAVE": attrs,
            "UNIDAD_PRECIO": p["unidad"],
            "CONTENIDO_UNIDAD": "" if p["mult"] in (None, "") else (f"{p['mult']:g}" if isinstance(p["mult"], (int, float)) else p["mult"]),
            "UNIDAD_CONTENIDO": p["unidad"] if p["mult"] not in (None, "") else "",
            "SKU": p["item"] or "", "GTIN_EAN": p["ean"], "URL_EASY": p["url"], "ES_PADRINO": SIN_PADRINO,
            "ESTADO": "Activo" if disp == "available" else (f"Sin stock en {CPA}" if disp else "Sin precio en Resistencia"),
            "OBSERVACIONES": AUTO + obs}


# ── Control de IVA antes de escribir ─────────────────────────────────────────
def auditar_iva(c, salida):
    errores = []
    for k, cols in MONETARIAS.items():
        for r in salida[k]:
            for col in cols:
                v = (r.get(col) or "").strip()
                if not v:
                    continue
                if not re.fullmatch(r"\d+\.\d{2}", v):
                    errores.append(f"{k}/{col}: valor no numérico {v!r}")
                elif v in c.gross_vistos and v not in c.netos_calculados:
                    errores.append(f"{k}/{col}: {v} coincide con un precio CON IVA de esta corrida ({r.get('ID_INSUMO')})")
    for r in salida["insumos"]:
        obs = r.get("OBSERVACIONES") or ""
        for num in re.findall(r"\d[\d.,]*", obs):
            if num.replace(".", "").replace(",", ".") in c.gross_vistos:
                errores.append(f"OBSERVACIONES de {r.get('ID_INSUMO')} menciona un importe con IVA ({num})")
    return errores


# ── Control.csv ──────────────────────────────────────────────────────────────
def armar_control(c, salida, R, estado, escritura, inicio):
    filas = []
    add = lambda s, k, v: filas.append({"SECCION": s, "CLAVE": k, "VALOR": v})
    add("Corrida", "Fecha", c.hoy)
    add("Corrida", "Inicio", inicio)
    add("Corrida", "Fin", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    add("Corrida", "Estado", estado)
    add("Corrida", "Pedidos al sitio", _n_pedidos)
    add("Ubicación", "Confirmada", "Sí" if c.cp_confirmado else "No")
    add("Ubicación", "Detalle", c.ubicacion_txt)
    add("IVA", "Todos los importes guardados están sin IVA",
        "Sí (auditoría previa a la escritura sin hallazgos)" if not R.get("errores_iva") else "NO — no se escribió")
    add("IVA", "Criterio", "precio de Easy ÷ (1 + alícuota), con la alícuota verificada contra el precio "
                           "sin impuestos nacionales publicado (21 / 10,5 / 27 %). Si no cierra, pendiente.")
    ins = salida["insumos"]
    add("Maestro", "Productos únicos", len({r["ID_INSUMO"] for r in ins if r.get("ID_INSUMO")}))
    add("Maestro", "Productos sin referencia pública", sum(1 for r in ins if not r.get("ID_INSUMO")))
    alic = {}
    for p in c.productos.values():
        if p.get("alic") is not None:
            alic[f"{p['alic'] * 100:.1f} %"] = alic.get(f"{p['alic'] * 100:.1f} %", 0) + 1
    add("Precios", "Vigentes netos cargados hoy", sum(1 for r in salida["precios"] if r["FECHA"] == c.hoy))
    add("Precios", "Vigentes en el archivo", len(salida["precios"]))
    add("Precios", "Pendientes en esta revisión", len(R["pendientes"]))
    add("Precios", "Última validación", c.hoy if any(r["FECHA"] == c.hoy for r in salida["precios"])
        else max((r["FECHA"] for r in salida["precios"]), default=""))
    add("Precios", "Alícuotas verificadas", ", ".join(f"{k}: {v}" for k, v in sorted(alic.items())))
    add("Precios", "Cambios de precio detectados", len(R["precio_cambios"]))
    for idi, a, b in R["precio_cambios"][:500]:
        add("Cambio de precio", idi, f"{a} → {b}")
    motivos = {}
    for idi, mot, ult in R["pendientes"]:
        motivos[mot] = motivos.get(mot, 0) + 1
    for mot, n in sorted(motivos.items(), key=lambda x: -x[1]):
        add("Pendientes por motivo", mot, n)
    for idi, mot, ult in R["pendientes"]:
        add("Precio pendiente", idi, f"{mot} · última verificación válida: {ult}")
    for idi, u_m, u_e in R.get("unidad_distinta", []):
        add("Unidad distinta", idi, f"el maestro dice «{u_m}» y Easy cobra por «{u_e}»: "
                                    "PRECIO_SIN_IVA es por la unidad de Easy")
    add("Padrinos", "Con cambio de precio", len(R["padrinos_cambio"]))
    for idi, a, b in R["padrinos_cambio"]:
        add("Padrino con cambio", idi, f"{a} → {b}")
    add("Padrinos", "Registros históricos agregados", R["hist_agregados"])
    add("Padrinos", "Candidatos «Agua Aduct» 110 mm × 4 m", " | ".join(R["padrino_candidatos"]) or
        "ninguno en el catálogo relevado: queda sin vincular")
    add("Promociones", "Nuevas", R["promo_nuevas"])
    add("Promociones", "Modificadas", R["promo_modif"])
    add("Promociones", "Vigentes", R["promo_vigentes"])
    add("Promociones", "Finalizadas en esta revisión", R["promo_fin"])
    add("Promociones", "Alcance", "precio tachado que Easy muestra para el CP 3506. Las promos condicionadas "
                                  "(por volumen, monto mínimo, banco o cuotas) no se registran: su precio depende "
                                  "de la compra y no hay un importe publicado por producto.")
    for rubro, d in c.por_rubro.items():
        add("Por rubro", rubro, f"{d['paginas']} páginas, {len(d['productos'])} productos")
    fuera = sum(1 for p in c.productos.values() if p["origen"] == "ficha")
    if fuera:
        add("Por rubro", "Fuera de los cuatro rubros (ya en el maestro)", f"{fuera} productos revisados por ficha")
    for n in c.nodos:
        url = BASE + n["ruta"]
        st = c.stats_nodo.get(url, {})
        add("Categoría", " > ".join(n["nombres"]),
            f"filtros: {st.get('filtros', 'sin leer')}, opciones: {st.get('opciones', '-')}, "
            f"productos Easy: {st.get('productos_easy', '-')}, cubiertos: {st.get('productos_cubiertos', '-')}"
            + (f", excluido por ser importe con IVA: {st['filtros_excluidos']}" if st.get("filtros_excluidos") else ""))
    add("Filtros", "Opciones vigentes", len(salida["filtros"]))
    add("Filtros", "Opciones nuevas", R["opciones_altas"])
    add("Filtros", "Opciones que dejaron de estar (quitadas del vigente)", len(R["opciones_bajas"]))
    for u, f, o in R["opciones_bajas"][:300]:
        add("Opción dada de baja", u, f"{f}: {o}")
    add("Clasificaciones", "Filas (atributo publicado × producto)", len(salida["clasif"]))
    add("Clasificaciones", "Productos con atributos", len({r["ID_INSUMO"] for r in salida["clasif"]}))
    add("Clasificaciones", "Clasificaciones distintas", len({r["CLASIFICACION"] for r in salida["clasif"]}))
    if not c.problemas:
        add("No cubierto", "—", "nada: todas las categorías, páginas y filtros se leyeron")
    for que, mot in c.problemas:
        add("No cubierto", que, mot)
    for k, v in escritura.items():
        add("Escritura Drive", k, v)
    add("Reintento", "Cómo", "Panel 8400 → job «Precios Easy» → Correr. Log local en "
                             f"{_state_dir() / 'logs'}. Una corrida fallida no toca los CSV.")
    return filas


# ── Principal ────────────────────────────────────────────────────────────────
def main():
    global log
    ap = argparse.ArgumentParser()
    ap.add_argument("--seco", action="store_true", help="no escribe en Drive")
    args = ap.parse_args()

    st = _state_dir()
    (st / "logs").mkdir(parents=True, exist_ok=True)
    inicio = datetime.now()
    log = Log(st / "logs" / f"precios_easy_{inicio:%Y%m%d_%H%M%S}.log")
    drive = _drive_dir()
    if not drive or not drive.is_dir():
        log(f"✗ No encuentro la carpeta de Drive «Precios Easy» ({drive}). Definí EASY_DRIVE_DIR "
            "o SIBRA_DRIVE. No se crea una carpeta nueva: escribiría fuera de lo sincronizado.")
        return 2

    with Candado(st / "corrida.lock"):
        c = Corrida()
        log(f"Precios Easy — {c.hoy} — Drive: {drive}")
        prev = {k: leer_csv(drive / ARCH[k]) for k in ARCH if k != "control"}
        try:
            c.ubicar()
            c.arbol()
            c.filtros()
            c.catalogo()
            c.maestro_fuera_de_alcance(prev["insumos"])
            log(f"productos únicos relevados: {len(c.productos)}")
            c.precios()
        except Bloqueado as e:
            c.problema("Sitio", f"Easy cortó el acceso y no se insiste: {e}")
        except Exception as e:
            c.problema("Relevamiento", f"error inesperado: {e}")
            log(traceback.format_exc())

        salida, R = fusionar(c, prev)
        R["errores_iva"] = auditar_iva(c, salida)
        escritura = {}
        if R["errores_iva"]:
            for e in R["errores_iva"][:50]:
                log("✗ IVA:", e)
            estado = "FALLIDA — la auditoría de IVA encontró importes dudosos; no se escribió nada"
        elif args.seco:
            estado = "SECA — no se escribió en Drive"
        else:
            bk = st / "respaldo" / inicio.strftime("%Y%m%d_%H%M%S")
            bk.mkdir(parents=True, exist_ok=True)
            for k in ARCH:
                if (drive / ARCH[k]).exists():
                    shutil.copy2(drive / ARCH[k], bk / ARCH[k])
            for viejo in sorted((st / "respaldo").iterdir())[:-10]:
                shutil.rmtree(viejo, ignore_errors=True)
            for k in ["insumos", "precios", "historico", "promos", "clasif", "filtros"]:
                try:
                    escribir_atomico(drive / ARCH[k], csv_texto(COLS[k], salida[k]))
                    escritura[ARCH[k]] = f"OK, {len(salida[k])} filas"
                except Exception as e:
                    escritura[ARCH[k]] = f"FALLÓ: {e}"
            mal = [k for k, v in escritura.items() if not v.startswith("OK")]
            if mal:
                estado = "FALLIDA — no se pudieron escribir: " + ", ".join(mal)
            elif c.problemas:
                estado = f"INCOMPLETA — {len(c.problemas)} puntos sin cubrir (ver «No cubierto»)"
            else:
                estado = "COMPLETA"
        control = armar_control(c, salida, R, estado, escritura, inicio.strftime("%Y-%m-%d %H:%M:%S"))
        if not args.seco:
            try:
                escribir_atomico(drive / ARCH["control"], csv_texto(COLS["control"], control))
            except Exception as e:
                estado = f"FALLIDA — no se pudo escribir el control: {e}"
        else:
            (st / "control_seco.csv").write_text(csv_texto(COLS["control"], control), encoding="utf-8-sig")

        log("── Resumen ──")
        for r in control:
            if r["SECCION"] in ("Precio pendiente", "Opción dada de baja", "Cambio de precio", "Categoría"):
                continue
            log(f"{r['SECCION']} · {r['CLAVE']}: {r['VALOR']}")
        log("ESTADO:", estado)
        return 0 if estado.startswith(("COMPLETA", "SECA")) else 1


if __name__ == "__main__":
    sys.exit(main())
