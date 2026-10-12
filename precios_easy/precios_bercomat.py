# -*- coding: utf-8 -*-
"""Relevamiento de catálogo y precios públicos de Familia Bercomat → CSV en Drive.

Zonas: Resistencia (CP 3506 → grupo de precios RS01) y Corrientes (CP 3400 →
CR01). Catálogo COMPLETO: de los cuatro rubros del job de Easy, Bercomat casi
no tiene Plomería y no tiene Electricidad, así que se releva todo y el Control
lo separa por rubro.

De dónde sale cada dato (lo mismo que consulta su tienda, catalogo.familiabercomat.com;
no tiene robots.txt, no pide login, y el reCAPTCHA está sólo en el pago):

    zona y precios   /api/catalog/by-cp?cp=<CP>          → contexto (ciudad, grupo
                                                           de precios), precio,
                                                           oferta, stock, facetas
    filtros          /api/catalog/by-cp?cp=<CP>&categoria1=…&categoria2=…
    atributos        /api/catalog/product/<sku>?cp=<CP>

⚠ IVA. Bercomat NO publica el IVA ni un precio sin impuestos. Por decisión de
Juan (2026-10-11): *«21% a todo»*. Se asume que el precio publicado es final
con IVA al 21 % y se guarda dividido por 1,21. Queda dicho en el Control de
cada corrida. En Easy el 10,5 % apareció sólo en material eléctrico puntual
(llaves, enchufes, instrumentos, estabilizadores, porteros): Bercomat no tiene
ese rubro.

El cronograma vive en el panel 8400 (`jobs_cronograma`, job `precios_bercomat`).

    python precios_bercomat.py            # corrida completa
    python precios_bercomat.py --seco     # releva y valida, no escribe en Drive
"""
import argparse
import os
import re
import shutil
import sys
import traceback
import urllib.parse
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import precios_easy as pe
from precios_easy import D, fmt, neto, leer_csv, csv_texto, escribir_atomico, Candado, Log, Bloqueado

BASE = "https://catalogo.familiabercomat.com"
API = BASE + "/api"
ZONAS = [  # (CP a guardar, CP que acepta Bercomat, ciudad esperada, provincia esperada)
    ("H3506", "3506", "Resistencia", "CC"),
    ("W3400", "3400", "Corrientes", "CR"),
]
IVA = Decimal("0.21")          # decisión de Juan, ver arriba
POR_PAGINA = 200               # el máximo que acepta la API
ESPERADOS = {"H3506": "RS01", "W3400": "CR01"}

PADRINO_AGUA_ADUCT = "Sí - padrino de «Agua Aduct»"
SIN_PADRINO = pe.SIN_PADRINO
AUTO = pe.AUTO

ARCH = {
    "insumos": "Precios Bercomat - Insumos.csv",
    "precios": "Precios Bercomat - Precios.csv",
    "historico": "Precios Bercomat - Histórico Padrinos.csv",
    "promos": "Precios Bercomat - Promociones.csv",
    "clasif": "Precios Bercomat - Clasificaciones.csv",
    "filtros": "Precios Bercomat - Filtros.csv",
    "control": "Precios Bercomat - Control.csv",
}
# Mismo modelo que Easy por dentro; en el archivo, el código y la URL dicen de quién son.
RENOMBRE = {"CODIGO_EASY": "CODIGO_BERCOMAT", "URL_EASY": "URL_BERCOMAT"}
COLS = {k: [RENOMBRE.get(c, c) for c in v] for k, v in pe.COLS.items()}
MONETARIAS = pe.MONETARIAS
CAMPOS_MANUALES = pe.CAMPOS_MANUALES
NOMBRE_FILTRO = {"categoria1": "Departamento", "categoria2": "Categoría", "categoria3": "Subcategoría",
                 "categoria4": "Subcategoría 2", "con_stock": "Con stock", "outlet": "Outlet",
                 "saldos": "Saldos", "envio": "Envío", "cuotas": "Cuotas",
                 "grupo_cobertura": "Grupo de cobertura", "unidad_base": "Unidad base",
                 "unidad_compra": "Unidad de compra"}

log = Log(None)


def _drive_dir():
    if os.environ.get("BERCOMAT_DRIVE_DIR"):
        return Path(os.environ["BERCOMAT_DRIVE_DIR"])
    raiz = os.environ.get("SIBRA_DRIVE") or (r"H:\My Drive" if os.name == "nt" else "")
    return Path(raiz) / "Precios Bercomat" if raiz else None


def _state_dir():
    if os.environ.get("BERCOMAT_STATE_DIR"):
        return Path(os.environ["BERCOMAT_STATE_DIR"])
    if os.name == "nt":
        return Path(r"C:\SIBRA\precios_bercomat")
    return Path.home() / ".local" / "state" / "precios_bercomat"


def _a_interno(filas):
    inv = {v: k for k, v in RENOMBRE.items()}
    return [{inv.get(k, k): v for k, v in r.items()} for r in filas]


def _a_archivo(filas):
    return [{RENOMBRE.get(k, k): v for k, v in r.items()} for r in filas]


def pedir(ruta, **params):
    return pe.pedir(API + ruta + ("?" + urllib.parse.urlencode(params, doseq=True) if params else ""))


def url_cat(cp, filtros):
    q = {"cp": cp, **{k: v for k, v in filtros}}
    return f"{BASE}/?{urllib.parse.urlencode(q)}"


class Corrida:
    def __init__(self):
        self.hoy = datetime.now().strftime("%Y-%m-%d")
        self.problemas = []
        self.zonas = {}           # cp_guardado → {"cp", "ok", "texto", "grupo"}
        self.productos = {}       # sku → dict
        self.filtros = {}         # cp_guardado → {url: [filas]}
        self.nodos = {}           # cp_guardado → [(filtros, total)]
        self.gross_vistos = set()
        self.netos_calculados = set()

    def problema(self, que, motivo):
        self.problemas.append((que, motivo))
        log("⚠", que, "—", motivo)

    # 1 · zonas
    def ubicar(self):
        for cpg, cp, ciudad, prov in ZONAS:
            try:
                ctx = pedir("/catalog/by-cp", cp=cp, page=1, pageSize=1).get("context") or {}
            except Exception as e:
                self.problema(f"Zona {cpg}", f"no se pudo consultar: {e}")
                continue
            ok = (ctx.get("cityLabel") or "").strip().lower() == ciudad.lower() and \
                 (ctx.get("provincia") or "").upper() == prov
            txt = (f"CP {cp} → {ctx.get('cityLabel')} ({ctx.get('ciudad')}), provincia {ctx.get('provincia')}, "
                   f"grupo de precios {ctx.get('grupoPrecios')}, zona {ctx.get('zoneId')}")
            if ctx.get("grupoPrecios") != ESPERADOS[cpg]:
                txt += f" ⚠ se esperaba {ESPERADOS[cpg]}"
            self.zonas[cpg] = {"cp": cp, "ok": ok, "texto": txt, "grupo": ctx.get("grupoPrecios")}
            if not ok:
                self.problema(f"Zona {cpg}", f"Bercomat no confirmó {ciudad}: {txt}. Esa zona no se carga")
            log("zona:", txt)

    # 2 · catálogo y precios por zona
    def catalogo(self):
        for cpg, z in self.zonas.items():
            if not z["ok"]:
                continue
            try:
                vistos, page, total, paginas = set(), 1, None, 0
                while True:
                    d = pedir("/catalog/by-cp", cp=z["cp"], page=page, pageSize=POR_PAGINA)
                    paginas += 1
                    total = int((d.get("pagination") or {}).get("total") or 0)
                    for it in d.get("items") or []:
                        self._tomar(it, cpg)
                        vistos.add(it.get("sku"))
                    if page >= int((d.get("pagination") or {}).get("totalPages") or 1) or not d.get("items"):
                        break
                    page += 1
                z.update(paginas=paginas, total=total, cubiertos=len(vistos))
                if len(vistos) < total:
                    self.problema(f"Productos {cpg}", f"Bercomat informa {total} y se obtuvieron {len(vistos)}")
                log(f"catálogo {cpg}: {len(vistos)} de {total} productos en {paginas} páginas")
            except Bloqueado:
                raise
            except Exception as e:
                self.problema(f"Productos {cpg}", f"corte en la paginación: {e}")

    def _tomar(self, it, cpg):
        sku = str(it.get("displaySku") or it.get("sku") or "").strip()
        if not sku:
            return
        p = self.productos.get(sku)
        if p is None:
            cat = it.get("category") or {}
            p = self.productos[sku] = {
                "ref": sku, "nombre": (it.get("name") or "").strip(),
                "niveles": {"RUBRO": cat.get("l1") or it.get("categoria1") or "",
                            "SUBRUBRO": cat.get("l2") or it.get("categoria2") or "",
                            "CATEGORIA": cat.get("l3") or it.get("categoria3") or "",
                            "SUBCATEGORIA": cat.get("l4") or it.get("categoria4") or ""},
                "unidad": it.get("unidadInventario") or it.get("unidad_inventario") or "",
                "factor": it.get("factorConversion") or it.get("factor_conversion"),
                "url": f"{BASE}/producto/{urllib.parse.quote(sku)}",
                "specs": None, "ofertas": {}, "zona_ficha": cpg,
            }
        lista, venta = it.get("price"), it.get("finalPrice", it.get("precio_oferta"))
        p["ofertas"][cpg] = {
            "lista": D(lista) if lista not in (None, "") else None,
            "venta": D(venta) if venta not in (None, "") else None,
            "oferta": bool(it.get("hasOffer")), "pct": it.get("discountPercent"),
            "disp": bool(it.get("isAvailable")), "stock": it.get("stock"),
        }

    # 3 · filtros, categoría por categoría y zona por zona
    def leer_filtros(self):
        for cpg, z in self.zonas.items():
            if not z["ok"]:
                continue
            self.filtros[cpg], self.nodos[cpg] = {}, []
            self._nodo(cpg, z["cp"], [])
            log(f"filtros {cpg}: {len(self.nodos[cpg])} categorías, "
                f"{sum(len(v) for v in self.filtros[cpg].values())} opciones")

    def _nodo(self, cpg, cp, filtros):
        try:
            d = pedir("/catalog/by-cp", cp=cp, page=1, pageSize=1, **dict(filtros))
        except Bloqueado:
            raise
        except Exception as e:
            self.problema(f"Filtros {cpg} {' > '.join(v for _, v in filtros) or '(todo)'}", str(e))
            return
        total = int((d.get("pagination") or {}).get("total") or 0)
        niveles = [v for _, v in filtros] + ["", "", "", ""]
        url = url_cat(cp, filtros)
        filas = []
        for clave, vals in (d.get("facets") or {}).items():
            for v in vals or []:
                op = v.get("value")
                op = "Sí" if op is True else ("No" if op is False else str(op))
                filas.append({"FECHA_ULTIMA_REVISION": self.hoy, "CODIGO_POSTAL": cpg,
                              "RUBRO": niveles[0], "SUBRUBRO": niveles[1], "CATEGORIA": niveles[2],
                              "SUBCATEGORIA": niveles[3], "FILTRO": NOMBRE_FILTRO.get(clave, clave),
                              "OPCION": op, "CANTIDAD_RESULTADOS": v.get("count", ""), "URL_CATEGORIA": url})
        self.filtros[cpg][url] = filas
        self.nodos[cpg].append((filtros, total, len({f["FILTRO"] for f in filas}), len(filas)))
        nivel = len(filtros) + 1
        if nivel <= 4:
            for v in (d.get("facets") or {}).get(f"categoria{nivel}") or []:
                if v.get("value") and int(v.get("count") or 0) > 0:
                    self._nodo(cpg, cp, filtros + [(f"categoria{nivel}", v["value"])])

    # 4 · atributos de la ficha (son del producto, no de la zona)
    def fichas(self):
        n = 0
        for sku, p in self.productos.items():
            cp = self.zonas[p["zona_ficha"]]["cp"]
            try:
                prod = pedir(f"/catalog/product/{urllib.parse.quote(sku)}", cp=cp).get("product") or {}
            except Bloqueado:
                raise
            except Exception as e:
                self.problema(f"Ficha {sku}", str(e))
                continue
            specs = []
            for a in prod.get("attributes") or []:
                nom, val = (a.get("name") or "").strip(), str(a.get("value") or "").strip()
                if nom and val and not re.search(r"precio|price", nom, re.I):
                    specs.append((nom, val, "Ficha de producto"))
            p["specs"] = specs
            n += 1
            if n % 500 == 0:
                log(f"fichas: {n}/{len(self.productos)}")

    # 5 · importes sin IVA
    def netos(self):
        for p in self.productos.values():
            for cpg, o in p["ofertas"].items():
                o["pend"] = ""
                if not o["lista"] or o["lista"] <= 0:
                    o["pend"] = "Bercomat no publica precio para esta zona"
                    continue
                venta = o["venta"] if o["venta"] and o["venta"] > 0 else o["lista"]
                self.gross_vistos |= {f"{o['lista']:.2f}", f"{venta:.2f}"}
                lista = max(o["lista"], venta)
                o["neto_lista"], o["neto_venta"] = neto(lista, IVA), neto(venta, IVA)
                o["promo"] = venta < lista - D("0.005")
                o["pct_calc"] = ((1 - venta / lista) * 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
                self.netos_calculados |= {fmt(o["neto_lista"]), fmt(o["neto_venta"])}


def _fila_insumo(p):
    marca = next((v for n, v, _ in p["specs"] or [] if n.lower() == "marca"), "")
    zonas = ", ".join(cp for cp, o in sorted(p["ofertas"].items()) if o["disp"])
    f = p["factor"]
    return {"ID_INSUMO": f"BERCOMAT-{p['ref']}", "CODIGO_EASY": p["ref"], "DESCRIPCION": p["nombre"],
            "MARCA": marca, **p["niveles"],
            "ATRIBUTOS_CLAVE": "; ".join(f"{n}: {v}" for n, v, _ in p["specs"] or []),
            "UNIDAD_PRECIO": p["unidad"],
            "CONTENIDO_UNIDAD": "" if f in (None, "", 1) else f"{f:g}" if isinstance(f, (int, float)) else str(f),
            "UNIDAD_CONTENIDO": "" if f in (None, "", 1) else f"{p['unidad']} por unidad de compra",
            "SKU": p["ref"], "GTIN_EAN": "", "URL_EASY": p["url"], "ES_PADRINO": SIN_PADRINO,
            "ESTADO": "Activo" if zonas else "Sin stock en las dos zonas",
            "OBSERVACIONES": AUTO + "IVA 21 % por criterio (Bercomat no publica el IVA)"
                             + (f"; disponible en {zonas}" if zonas else "")}


def fusionar(c, prev):
    hoy = c.hoy
    R = {"precio_cambios": [], "padrinos_cambio": [], "hist_agregados": 0, "promo_nuevas": 0,
         "promo_modif": 0, "promo_fin": 0, "pendientes": []}
    zonas_ok = {cp for cp, z in c.zonas.items() if z["ok"] and z.get("cubiertos")}

    insumos, ya = [], set()
    for m in prev["insumos"]:
        ref = (m.get("CODIGO_EASY") or "").strip()
        p = c.productos.get(ref)
        ya.add(ref)
        if p and p["specs"] is not None:
            nuevo = _fila_insumo(p)
            for k in CAMPOS_MANUALES:
                if not (m.get(k) or "").strip():
                    m[k] = nuevo[k]
            m["ESTADO"] = nuevo["ESTADO"]
            if not m.get("OBSERVACIONES") or m["OBSERVACIONES"].startswith(AUTO):
                m["OBSERVACIONES"] = nuevo["OBSERVACIONES"]
        elif ref and not p and zonas_ok == {z[0] for z in ZONAS}:
            m["ESTADO"] = f"No encontrado en la revisión {hoy}"
        insumos.append(m)
    for ref, p in c.productos.items():
        if ref not in ya and p["specs"] is not None:
            insumos.append(_fila_insumo(p))

    cand = [m for m in insumos if re.search(r"a\w?aduct", (m.get("DESCRIPCION") or "") + " " + (m.get("MARCA") or ""), re.I)
            and re.search(r"\b110\b", m.get("DESCRIPCION") or "")
            and re.search(r"\b4\s*(m|mt|mts|metros)\b", m.get("DESCRIPCION") or "", re.I)]
    R["padrino_candidatos"] = [f"{m['ID_INSUMO']} {m['DESCRIPCION']}" for m in cand]
    if len(cand) == 1 and (cand[0].get("ES_PADRINO") or SIN_PADRINO) == SIN_PADRINO:
        cand[0]["ES_PADRINO"] = PADRINO_AGUA_ADUCT
    padrinos = {m["ID_INSUMO"] for m in insumos if (m.get("ES_PADRINO") or "").startswith("Sí")}

    precios = {(r["ID_INSUMO"], r["CODIGO_POSTAL"]): r for r in prev["precios"]}
    for ref, p in c.productos.items():
        idi = f"BERCOMAT-{ref}"
        for cpg, o in p["ofertas"].items():
            antes = precios.get((idi, cpg))
            if o["pend"]:
                R["pendientes"].append((f"{idi} {cpg}", o["pend"], antes["FECHA"] if antes else "nunca"))
                continue
            nuevo = fmt(o["neto_lista"])
            if antes and antes["PRECIO_SIN_IVA"] != nuevo:
                R["precio_cambios"].append((f"{idi} {cpg}", antes["PRECIO_SIN_IVA"], nuevo))
            precios[(idi, cpg)] = {"FECHA": hoy, "ID_INSUMO": idi, "CODIGO_POSTAL": cpg, "PRECIO_SIN_IVA": nuevo}

    hist = list(prev["historico"])
    for (idi, cpg), r in precios.items():
        if idi not in padrinos or r["FECHA"] != hoy:
            continue
        mios = [h for h in hist if h["ID_INSUMO"] == idi and h["CODIGO_POSTAL"] == cpg]
        ult = max(mios, key=lambda h: (h["FECHA_DESDE"], h["FECHA_ULTIMA_REVISION"]), default=None)
        if ult and ult["PRECIO_SIN_IVA"] == r["PRECIO_SIN_IVA"]:
            ult["FECHA_ULTIMA_REVISION"] = hoy
        else:
            if ult:
                R["padrinos_cambio"].append((f"{idi} {cpg}", ult["PRECIO_SIN_IVA"], r["PRECIO_SIN_IVA"]))
            hist.append({"FECHA_DESDE": hoy, "FECHA_ULTIMA_REVISION": hoy, "ID_INSUMO": idi,
                         "CODIGO_POSTAL": cpg, "PRECIO_SIN_IVA": r["PRECIO_SIN_IVA"]})
            R["hist_agregados"] += 1

    promos = list(prev["promos"])
    clave = lambda x: (x["PRECIO_LISTA_SIN_IVA"], x["PRECIO_PROMOCIONAL_SIN_IVA"], x["DESCUENTO_PCT"], x["VIGENCIA"])
    for ref, p in c.productos.items():
        idi = f"BERCOMAT-{ref}"
        for cpg, o in p["ofertas"].items():
            if o["pend"]:
                continue
            vig = [x for x in promos if x["ID_INSUMO"] == idi and x["CODIGO_POSTAL"] == cpg
                   and x["ESTADO_PROMOCION"] == "Vigente"]
            if not o["promo"]:
                for x in vig:
                    x["ESTADO_PROMOCION"] = "Finalizada"
                    R["promo_fin"] += 1
                continue
            fila = {"FECHA_DETECCION": hoy, "FECHA_ULTIMA_REVISION": hoy, "CODIGO_POSTAL": cpg,
                    "ID_INSUMO": idi, "CODIGO_EASY": ref, "DESCRIPCION": p["nombre"],
                    "PRECIO_LISTA_SIN_IVA": fmt(o["neto_lista"]), "PRECIO_PROMOCIONAL_SIN_IVA": fmt(o["neto_venta"]),
                    "DESCUENTO_PCT": f"{o['pct_calc']:.2f}", "VIGENCIA": "", "ESTADO_PROMOCION": "Vigente",
                    "URL_EASY": p["url"]}
            igual = [x for x in vig if clave(x) == clave(fila)]
            if igual:
                igual[0]["FECHA_ULTIMA_REVISION"] = hoy
                continue
            for x in vig:
                x["ESTADO_PROMOCION"] = "Finalizada"
            R["promo_modif" if vig else "promo_nuevas"] += 1
            promos.append(fila)
    R["promo_vigentes"] = sum(1 for x in promos if x["ESTADO_PROMOCION"] == "Vigente")

    con_ficha = {f"BERCOMAT-{r}" for r, p in c.productos.items() if p["specs"] is not None}
    clasif = [r for r in prev["clasif"] if r["ID_INSUMO"] not in con_ficha]
    for ref, p in c.productos.items():
        if p["specs"] is None:
            continue
        vistos = set()
        for n, v, o in p["specs"]:
            if (n, v) in vistos:
                continue
            vistos.add((n, v))
            clasif.append({"FECHA_ULTIMA_REVISION": hoy, "CODIGO_POSTAL": p["zona_ficha"], "ID_INSUMO": f"BERCOMAT-{ref}",
                           "CODIGO_EASY": ref, **p["niveles"], "CLASIFICACION": n, "VALOR": v, "ORIGEN": o,
                           "URL_EASY": p["url"]})

    leidas = {u for cpg in c.filtros for u in c.filtros[cpg]}
    filtros = [r for r in prev["filtros"] if r["URL_CATEGORIA"] not in leidas]
    previas = {(r["URL_CATEGORIA"], r["FILTRO"], r["OPCION"]) for r in prev["filtros"] if r["URL_CATEGORIA"] in leidas}
    actuales = set()
    for cpg in c.filtros:
        for filas in c.filtros[cpg].values():
            filtros.extend(filas)
            actuales |= {(r["URL_CATEGORIA"], r["FILTRO"], r["OPCION"]) for r in filas}
    R["opciones_bajas"] = sorted(previas - actuales)
    R["opciones_altas"] = len(actuales - previas)

    return {"insumos": insumos, "precios": sorted(precios.values(), key=lambda r: (r["ID_INSUMO"], r["CODIGO_POSTAL"])),
            "historico": hist, "promos": promos, "clasif": clasif, "filtros": filtros}, R


def armar_control(c, salida, R, estado, escritura, inicio):
    filas = []
    add = lambda s, k, v: filas.append({"SECCION": s, "CLAVE": k, "VALOR": v})
    add("Corrida", "Fecha", c.hoy)
    add("Corrida", "Inicio", inicio)
    add("Corrida", "Fin", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    add("Corrida", "Estado", estado)
    add("Corrida", "Pedidos al sitio", pe._n_pedidos)
    for cpg, z in c.zonas.items():
        add("Ubicación", cpg, ("Confirmada · " if z["ok"] else "NO confirmada · ") + z["texto"])
    add("IVA", "Todos los importes guardados están sin IVA",
        "Sí, al 21 % (auditoría previa a la escritura sin hallazgos)" if not R.get("errores_iva") else "NO — no se escribió")
    add("IVA", "Criterio", "Bercomat no publica el IVA ni un precio sin impuestos. Por decisión de Juan "
                           "(11/10/2026) se toma 21 % para todo: importe publicado ÷ 1,21. En Easy el 10,5 % "
                           "apareció sólo en material eléctrico puntual; Bercomat no tiene ese rubro.")
    ins = salida["insumos"]
    add("Maestro", "Productos únicos", len({r["ID_INSUMO"] for r in ins if r.get("ID_INSUMO")}))
    for cpg in sorted(c.zonas):
        hoy_cp = [r for r in salida["precios"] if r["CODIGO_POSTAL"] == cpg]
        add("Precios", f"Vigentes netos cargados hoy {cpg}", sum(1 for r in hoy_cp if r["FECHA"] == c.hoy))
        add("Precios", f"Vigentes en el archivo {cpg}", len(hoy_cp))
    add("Precios", "Pendientes en esta revisión", len(R["pendientes"]))
    add("Precios", "Última validación", max((r["FECHA"] for r in salida["precios"]), default=""))
    add("Precios", "Cambios de precio detectados", len(R["precio_cambios"]))
    for k, a, b in R["precio_cambios"][:500]:
        add("Cambio de precio", k, f"{a} → {b}")
    for k, mot, ult in R["pendientes"]:
        add("Precio pendiente", k, f"{mot} · última verificación válida: {ult}")
    dif = 0
    for p in c.productos.values():
        o = p["ofertas"]
        if len(o) == 2 and all(not x["pend"] for x in o.values()):
            a, b = list(o.values())
            dif += a["neto_lista"] != b["neto_lista"]
    add("Precios", "Productos con precio distinto entre zonas", dif)
    add("Padrinos", "Con cambio de precio", len(R["padrinos_cambio"]))
    for k, a, b in R["padrinos_cambio"]:
        add("Padrino con cambio", k, f"{a} → {b}")
    add("Padrinos", "Registros históricos agregados", R["hist_agregados"])
    add("Padrinos", "Candidatos «Agua Aduct» 110 mm × 4 m", " | ".join(R["padrino_candidatos"]) or
        "ninguno en el catálogo de Bercomat: queda sin vincular")
    for k in ("nuevas", "modif", "vigentes", "fin"):
        add("Promociones", {"nuevas": "Nuevas", "modif": "Modificadas", "vigentes": "Vigentes",
                            "fin": "Finalizadas en esta revisión"}[k], R[f"promo_{k}"])
    add("Promociones", "Alcance", "precio de oferta que Bercomat publica por zona (finalPrice contra price).")
    for cpg, z in c.zonas.items():
        if z.get("total") is not None:
            add("Por zona", cpg, f"{z.get('paginas')} páginas, {z.get('cubiertos')} de {z.get('total')} productos")
    rub = {}
    for p in c.productos.values():
        rub[p["niveles"]["RUBRO"] or "(sin rubro)"] = rub.get(p["niveles"]["RUBRO"] or "(sin rubro)", 0) + 1
    for r, n in sorted(rub.items(), key=lambda x: -x[1]):
        add("Por rubro", r, f"{n} productos")
    for cpg, nodos in c.nodos.items():
        for filtros, total, nf, no in nodos:
            add("Categoría", f"{cpg} · " + (" > ".join(v for _, v in filtros) or "(catálogo completo)"),
                f"filtros: {nf}, opciones: {no}, productos: {total}")
    add("Filtros", "Opciones vigentes", len(salida["filtros"]))
    add("Filtros", "Opciones nuevas", R["opciones_altas"])
    add("Filtros", "Opciones que dejaron de estar (quitadas del vigente)", len(R["opciones_bajas"]))
    for u, f, o in R["opciones_bajas"][:300]:
        add("Opción dada de baja", u, f"{f}: {o}")
    add("Clasificaciones", "Filas (atributo publicado × producto)", len(salida["clasif"]))
    add("Clasificaciones", "Productos con atributos", len({r["ID_INSUMO"] for r in salida["clasif"]}))
    add("Clasificaciones", "Clasificaciones distintas", len({r["CLASIFICACION"] for r in salida["clasif"]}))
    if not c.problemas:
        add("No cubierto", "—", "nada: las dos zonas, todas las páginas, categorías y fichas se leyeron")
    for que, mot in c.problemas:
        add("No cubierto", que, mot)
    for k, v in escritura.items():
        add("Escritura Drive", k, v)
    add("Reintento", "Cómo", "Panel 8400 → job «Precios Bercomat» → Correr. Log local en "
                             f"{_state_dir() / 'logs'}. Una corrida fallida no toca los CSV.")
    return filas


def main():
    global log
    ap = argparse.ArgumentParser()
    ap.add_argument("--seco", action="store_true", help="no escribe en Drive")
    args = ap.parse_args()

    st = _state_dir()
    (st / "logs").mkdir(parents=True, exist_ok=True)
    inicio = datetime.now()
    log = Log(st / "logs" / f"precios_bercomat_{inicio:%Y%m%d_%H%M%S}.log")
    drive = _drive_dir()
    if not drive or not drive.is_dir():
        log(f"✗ No encuentro la carpeta de Drive «Precios Bercomat» ({drive}). Definí BERCOMAT_DRIVE_DIR "
            "o SIBRA_DRIVE. No se crea una carpeta nueva: escribiría fuera de lo sincronizado.")
        return 2

    with Candado(st / "corrida.lock"):
        c = Corrida()
        log(f"Precios Bercomat — {c.hoy} — Drive: {drive}")
        prev = {k: _a_interno(leer_csv(drive / ARCH[k])) for k in ARCH if k != "control"}
        try:
            c.ubicar()
            c.catalogo()
            c.leer_filtros()
            c.fichas()
            c.netos()
        except Bloqueado as e:
            c.problema("Sitio", f"Bercomat cortó el acceso y no se insiste: {e}")
        except Exception as e:
            c.problema("Relevamiento", f"error inesperado: {e}")
            log(traceback.format_exc())
        for p in c.productos.values():      # si se cortó antes de netos()
            for o in p["ofertas"].values():
                o.setdefault("pend", "la corrida se cortó antes de calcular el neto")
        log(f"productos únicos relevados: {len(c.productos)}")

        salida, R = fusionar(c, prev)
        R["errores_iva"] = pe.auditar_iva(c, salida)
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
                    escribir_atomico(drive / ARCH[k], csv_texto(COLS[k], _a_archivo(salida[k])))
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
