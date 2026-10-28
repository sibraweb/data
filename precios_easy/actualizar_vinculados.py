# -*- coding: utf-8 -*-
"""Refresca el precio de lo que YA está vinculado a un insumo Sibratech (Easy y Bercomat).

Es el segundo nivel del circuito de mercado (Juan, 2026-10-12): la base completa de
cada proveedor se baja de vez en cuando (precios_easy.py, precios_bercomat.py);
esto sólo consulta los productos de `vinculos_precios` y deja una cotización nueva
en `cotizaciones` SÓLO cuando el precio cambió. Si es el mismo, se pisa la fecha de la última línea
(Juan, 2026-10-27): así la tabla guarda la curva de variación y no una fila por cada pasada.

  · Easy      una ficha por producto (alternateIds_RefId) + simulación de carrito en
              CP 3506; el neto sale del «sin impuestos» verificado contra 21/10,5/27 %.
  · Bercomat  una pasada por el catálogo de la zona H3506 (unos 30 s); neto = precio ÷ 1,21.

El precio queda por unidad de compra del proveedor; el APU lo convierte con el `coef`
del vínculo. No escribe nada en Drive ni en ningún .bc3.

    python actualizar_vinculados.py                 # en seco
    python actualizar_vinculados.py --aplicar       # escribe cotizaciones
    python actualizar_vinculados.py --solo easy     # o bercomat
"""
import argparse
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, r"C:\Users\juanb\OneDrive\Desktop\Proyectos CODE\sibra-obra-repo\api")
import db  # noqa: E402
import precios_bercomat as pb  # noqa: E402
import precios_easy as pe  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PROVEEDORES = {"251": ("EASY", "EASY-", "H3506", "EASY:precios_easy"),
               "96": ("bercomat", "BERCOMAT-", "H3506", "BERCOMAT:precios_bercomat")}
# «Cambió» = difiere al centavo. Línea nueva sólo si cambió; si no, se pisa la fecha de la última.

_LOG = []


def log(*a):
    txt = f"{datetime.now():%H:%M:%S} " + " ".join(str(x) for x in a)
    _LOG.append(txt)
    print(txt)


pe.log = pb.log = log


def vinculos():
    return db.query("select id_proveedor, cod_prov, cod_sibra, coef from vinculos_precios "
                    "where id_proveedor = any(%s) and activo='1' order by id", (list(PROVEEDORES),))


def precios_easy(refs):
    c = pe.Corrida()
    c.ubicar()
    for ref in refs:
        try:
            # el código del vínculo es el id de producto de Easy; en algunos productos la
            # «referencia» pública es el EAN, así que se busca primero por productId
            r = pe.pedir(f"{pe.BASE}/api/catalog_system/pub/products/search?" + pe._q(fq=f"productId:{ref}"))
            if not r:
                r = pe.pedir(f"{pe.BASE}/api/catalog_system/pub/products/search?" + pe._q(fq=f"alternateIds_RefId:{ref}"))
        except pe.Bloqueado:
            raise
        except Exception as e:
            log(f"  ✗ Easy {ref}: {e}")
            continue
        if r:
            c._tomar(c._de_legacy(r[0]), "vinculado", "ficha")
        else:
            log(f"  ✗ Easy {ref}: no aparece (¿dado de baja?)")
    c.precios()
    out = {}
    for p in c.productos.values():
        res = (float(p["neto_lista"]), "") if p.get("alic") and p.get("neto_lista") else (None, p.get("pend") or "sin precio")
        for k in {str(p.get("pid")), str(p.get("item")), str(p.get("ref"))}:
            out.setdefault(k, res)
    return out


def precios_bercomat(skus):
    c = pb.Corrida()
    c.ubicar()
    c.catalogo()
    c.netos()
    out = {}
    for sku in skus:
        p = c.productos.get(sku)
        o = (p or {}).get("ofertas", {}).get("H3506")
        if o and o.get("neto_lista"):
            out[sku] = (float(o["neto_lista"]), "")
        else:
            out[sku] = (None, (o or {}).get("pend") or "no está en el catálogo de la zona")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--solo", choices=["easy", "bercomat"])
    args = ap.parse_args()
    vin = vinculos()
    log(f"vínculos activos: {len(vin)} · {'ESCRIBE' if args.aplicar else 'en seco'}")
    st = pe._state_dir()
    with pe.Candado(st / "vinculados.lock"):
        nuevas = pisadas = 0
        for idp, (nombre, pref, zona, origen) in PROVEEDORES.items():
            if args.solo and args.solo != nombre.lower():
                continue
            vs = [v for v in vin if v["id_proveedor"] == idp]
            if not vs:
                log(f"{nombre}: sin vínculos")
                continue
            claves = sorted({v["cod_prov"][len(pref):] for v in vs})
            try:
                got = precios_easy(claves) if idp == "251" else precios_bercomat(claves)
            except Exception as e:
                log(f"✗ {nombre}: {e}")
                log(traceback.format_exc())
                continue
            for cod_prov in sorted({v["cod_prov"] for v in vs}):
                precio, motivo = got.get(cod_prov[len(pref):], (None, "sin respuesta"))
                destinos = ", ".join(f"{v['cod_sibra']}×{v['coef']}" for v in vs if v["cod_prov"] == cod_prov)
                if precio is None:
                    log(f"  ⚠ {cod_prov:20} → {destinos}: {motivo}")
                    continue
                ult = db.query("select id, precio, fecha from cotizaciones where id_proveedor=%s and cod_prov=%s "
                               "order by fecha desc, id desc limit 1", (idp, cod_prov))
                ant = float(ult[0]["precio"]) if ult else None
                igual = ant is not None and round(precio, 2) == round(ant, 2)
                cambio = None if not ant else (precio - ant) / ant
                escribir = not igual
                marca = "NUEVA" if ant is None else (f"{cambio:+.1%}" if not igual else "igual · fecha al día")
                log(f"  {'→' if escribir else '·'} {cod_prov:20} ${precio:>11,.2f}  ({marca})  {destinos}")
                if igual and args.aplicar and ult[0]["fecha"][:10] != date.today().isoformat():
                    hoy = date.today().isoformat()
                    db.execute("update cotizaciones set fecha=%s, fecha_carga=%s where id=%s", (hoy, hoy, ult[0]["id"]))
                    pisadas += 1
                if escribir and args.aplicar:
                    n = (db.query("select max(substring(id from 5)::int) m from cotizaciones where id ~ '^COT-[0-9]+$'")[0]["m"] or 0) + 1
                    v0 = next(v for v in vs if v["cod_prov"] == cod_prov)
                    s = db.query("select descripcion, unidad from insumos where cod_sibra=%s", (v0["cod_sibra"],))[0]
                    hoy = date.today().isoformat()
                    db.execute("insert into cotizaciones (id, cod_insumo, descripcion, unidad, fecha, precio, moneda, id_proveedor, "
                               "proveedor, lugar_entrega, notas, origen, usuario, fecha_carga, cod_prov) "
                               "values (%s,%s,%s,%s,%s,%s,'ARS',%s,%s,%s,%s,%s,%s,%s,%s)",
                               (f"COT-{n:05d}", v0["cod_sibra"], s["descripcion"], s["unidad"], hoy, f"{precio:.4f}", idp, nombre,
                                "Resistencia (CP 3506)", f"{nombre} {zona} neto · {marca}", origen, "actualizar-vinculados", hoy, cod_prov))
                    nuevas += 1
        log(f"cotizaciones nuevas (el precio cambió): {nuevas} · fechas al día (mismo precio): {pisadas}")
    d = st / "logs"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"vinculados_{datetime.now():%Y%m%d_%H%M%S}.log").write_text("\n".join(_LOG), encoding="utf-8")


if __name__ == "__main__":
    main()
