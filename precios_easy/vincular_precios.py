# -*- coding: utf-8 -*-
"""Vincula productos de Easy / Bercomat con insumos Sibratech y graba su precio.

Entrada: un JSON en `vinculos/` con la lista de vínculos confirmados por Juan:
    {"proveedor": "EASY", "id_proveedor": "251", "csv_insumos": ..., "csv_precios": ..., "zona": "H3506",
     "origen": "EASY:precios_easy", "vinculos": [
        {"cod_sibra": "P41DU001", "id_producto": "EASY-1324905", "coef": "1/30",
         "presentacion": "rollo 30 m", "nota": "..."}]}

Escribe en dos tablas (las mismas que usa /apu/precios-mercado):
  · `vinculos_precios`  cod_prov (id del producto) → cod_sibra, con `coef`
  · `cotizaciones`     el precio NETO de IVA del proveedor, por unidad de compra

El APU calcula  precio_sibra = precio_proveedor × coef.  Un rollo de 30 m para un
insumo en ML lleva coef 1/30; un pack de 12 cajas, 1/12.

La marca, la línea y la presentación del producto elegido quedan en `desc_prov` y
`notas` del vínculo: de ahí sale el texto de los MOD («pintura …, caños …»).

    python vincular_precios.py vinculos/mod1_electricidad.json            # en seco
    python vincular_precios.py vinculos/mod1_electricidad.json --aplicar  # escribe
Es idempotente: no duplica un vínculo ni una cotización del mismo día.
"""
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, r"C:\Users\juanb\OneDrive\Desktop\Proyectos CODE\sibra-obra-repo\api")
import db  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass



OBRA_URL = os.environ.get("OBRA_URL", "http://localhost:8000").rstrip("/")


def _por_la_puerta(body):
    """Graba un vínculo por la PUERTA ÚNICA del sistema (`POST /maestros/crosswalk/aprender`):
    valida que el insumo exista, reactiva un vínculo dado de baja, recupera precios que
    habían entrado sin insumo y limpia el caché. Devuelve el JSON, o None si el servidor
    no está (se cae a escribir la tabla directo, con las mismas reglas)."""
    try:
        req = urllib.request.Request(OBRA_URL + "/maestros/crosswalk/aprender",
                                     data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"la puerta rechazó el vínculo {body.get('cod_prov')}→{body.get('cod_sibra')}: {e.read().decode('utf-8', 'replace')[:200]}")
    except Exception:
        return None


def _coef(txt):
    """«1/30», «1/0.9» o «0.25» -> texto decimal."""
    partes = str(txt).split("/")
    f = Fraction(partes[0].strip())
    for d in partes[1:]:
        f = f / Fraction(d.strip())
    return f"{float(f):.6f}".rstrip("0").rstrip(".")


def _leer(csv_path, clave):
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        return {r[clave]: r for r in csv.DictReader(fh)}


def main(argv):
    ruta = Path(argv[1])
    aplicar = "--aplicar" in argv
    cfg = json.loads(ruta.read_text(encoding="utf-8"))
    ins = _leer(cfg["csv_insumos"], "ID_INSUMO")
    precios = {}
    with open(cfg["csv_precios"], encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["CODIGO_POSTAL"] == cfg["zona"]:
                precios[r["ID_INSUMO"]] = (r["FECHA"], float(r["PRECIO_SIN_IVA"]))
    insumos = {r["cod_sibra"]: r for r in db.query("select cod_sibra, descripcion, unidad from insumos")}
    hoy = date.today().isoformat()
    ult_vin = db.query("select max(substring(id_vinculo from 5)::int) m from vinculos_precios "
                       "where id_vinculo ~ '^VIN-[0-9]+$'")[0]["m"] or 0
    ult_cot = db.query("select max(substring(id from 5)::int) m from cotizaciones "
                       "where id ~ '^COT-[0-9]+$'")[0]["m"] or 0
    nv = nc = 0
    for v in cfg["vinculos"]:
        pid, cod = v["id_producto"], v["cod_sibra"]
        p, i, s = precios.get(pid), ins.get(pid), insumos.get(cod)
        if not (p and i and s):
            print(f"  ✗ {cod:11} {pid}: falta " + ("precio " if not p else "") + ("producto " if not i else "") + ("insumo " if not s else ""))
            continue
        coef = _coef(v["coef"])
        fecha, precio = p
        marca = i.get("MARCA", "")
        desc_prov = i["DESCRIPCION"]
        notas = " · ".join(x for x in (marca, v.get("presentacion", ""), v.get("nota", ""),
                                       f"{cfg['proveedor']} {cfg['zona']} neto") if x)
        sibra_u = precio * float(coef)
        print(f"  ✓ {cod:11} ← {pid:14} {desc_prov[:46]:46} ${precio:>10,.2f} × {coef:>9} = ${sibra_u:>9,.2f}/{s['unidad']}")
        if not aplicar:
            continue
        r = _por_la_puerta({"id_proveedor": cfg["id_proveedor"], "nombre_proveedor": cfg["proveedor"], "cod_prov": pid,
                            "cod_sibra": cod, "coef": float(coef), "desc_prov": desc_prov,
                            "un_prov": v.get("presentacion", ""), "notas": notas})
        ya = db.query("select 1 from vinculos_precios where id_proveedor=%s and cod_prov=%s and cod_sibra=%s",
                      (cfg["id_proveedor"], pid, cod))
        if r is not None:
            nv += 1 if r.get("nuevo") else 0
            print(f"      (por la puerta del ERP: {'nuevo' if r.get('nuevo') else 'ya existía'})")
        elif not ya:
            ult_vin += 1
            db.execute("insert into vinculos_precios (id, id_vinculo, id_proveedor, nombre_proveedor, cod_prov, "
                       "desc_prov, un_prov, cod_sibra, desc_sibra, coef, activo, notas, fecha_actualizacion) "
                       "values ((select coalesce(max(id),0)+1 from vinculos_precios),%s,%s,%s,%s,%s,%s,%s,%s,%s,'1',%s,%s)",
                       (f"VIN-{ult_vin:05d}", cfg["id_proveedor"], cfg["proveedor"], pid, desc_prov,
                        v.get("presentacion", ""), cod, s["descripcion"], coef, notas, hoy))
            nv += 1
        yc = db.query("select 1 from cotizaciones where id_proveedor=%s and cod_prov=%s and fecha=%s",
                      (cfg["id_proveedor"], pid, fecha))
        if not yc:
            ult_cot += 1
            db.execute("insert into cotizaciones (id, cod_insumo, descripcion, unidad, fecha, precio, moneda, "
                       "id_proveedor, proveedor, lugar_entrega, notas, origen, usuario, fecha_carga, cod_prov) "
                       "values (%s,%s,%s,%s,%s,%s,'ARS',%s,%s,%s,%s,%s,%s,%s,%s)",
                       (f"COT-{ult_cot:05d}", cod, s["descripcion"], v.get("presentacion", "") or s["unidad"], fecha,
                        f"{precio:.4f}", cfg["id_proveedor"], cfg["proveedor"], cfg.get("lugar", ""),
                        notas, cfg["origen"], "vinculacion-mod1", hoy, pid))
            nc += 1
    if aplicar:
        print(f"\nEscrito: {nv} vínculos nuevos, {nc} cotizaciones nuevas.")
    else:
        print("\n(en seco: no se escribió nada; agregar --aplicar)")


if __name__ == "__main__":
    main(sys.argv)
