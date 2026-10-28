# -*- coding: utf-8 -*-
"""Histórico de las tasas ACTIVAS del Banco Nación (BNA_TASAS), desde Ámbito.

Receta completa y trampas en `indices/PENDIENTE__HISTORICO_TASAS_BNA_AMBITO.md`.
Las páginas de Ámbito montan un iframe a una planilla de Google PUBLICADA: se
baja con un GET común, una hoja por año.

Uso:  python api/cargar_bna_ambito.py            → simulacro (muestra, no escribe)
      python api/cargar_bna_ambito.py --aplicar  → escribe en BNA_TASAS
      --anios 2025,2026                          → qué años (default 2025 y 2026)

⚠ SOLO SE CARGAN LOS AÑOS CUYA CABECERA COINCIDE con la que este parser conoce
(Fecha · Cartera general · Adelanto con acuerdo · Descubiertos: hipotecaria,
solicitado, no solicitado TASA y CFT, cada uno TNA/TEA). La estructura cambia
entre años —en 2018 la cartera se abre en Diversas/Agropecuaria—; un año con
otra cabecera se SALTEA y se dice, no se carga desalineado: poner a una tasa el
nombre de otra es el peor error posible acá, porque el número sigue siendo
verosímil.

⚠ Las fechas vienen AGRUPADAS POR RANGO cuando la tasa no cambió («12 AL
15/06/2026», «29/4/26 al 30/04/26»): se expanden a días calendario.
⚠ `s/d` = no se publicó (no es cero) → la celda no se carga.
⚠ Hay comas donde van puntos (`26,02`): se normaliza. Un valor que se aparta
más de 40 % del día anterior se avisa (no se frena: puede ser un cambio real).
⚠ APPEND-ONLY (ON CONFLICT DO NOTHING): lo que el relevamiento diario ya
guardó no se pisa.
"""
import os
import re
import sys
import datetime as dt

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")
AQUI = os.path.dirname(os.path.abspath(__file__))

KEY = "2PACX-1vQO9BxwDGXL5EIr0rAohUuAr10Fi3hiYPHQfTNCN17opmNz2IGHiSKEEPTFR-3FvYbPQKmEi1Dw6Hoh"
HOJA = "https://docs.google.com/spreadsheets/d/e/%s/pubhtml/sheet?headers=false&gid=%s"
GIDS = {2025: 2029045132, 2026: 1771614277, 2023: 1649749500, 2022: 1308278990, 2021: 1541919325}

# Orden de las columnas TNA tras la fecha (cada una va seguida de su TEA).
# El último par (CFT) no se carga: no es una tasa nominal comparable.
COLUMNAS = ["CARTERA_GENERAL", "ADELANTOS_ACUERDO", "DESCUBIERTO_HIPOTECARIA",
            "DESCUBIERTO_SOLICITADO", "DESCUBIERTO_NO_SOLICITADO"]
ESPERADO = ["fecha", "tasa de cartera general", "adelanto cta. cte. con acuerdo", "descubiertos en cta cte"]


def _fecha(txt, ref=None, anio=None):
    """'6/1/2026' / '12' / '29/4/26' → date. `ref` completa mes y año faltantes."""
    p = [x for x in re.split(r"[/\-.]", txt.strip()) if x]
    d = int(p[0])
    m = int(p[1]) if len(p) > 1 else ref.month
    y = int(p[2]) if len(p) > 2 else (ref.year if ref else anio)
    if y < 100:
        y += 2000
    return dt.date(y, m, d)


def dias(celda, anio=None):
    """Una celda de fecha (suelta o rango) → lista de días calendario."""
    t = celda.strip()
    if re.search(r"\s+al\s+", t, re.I):
        a, b = re.split(r"\s+al\s+", t, flags=re.I)
        fin = _fecha(b, anio=anio)
        ini = _fecha(a, ref=fin)
        n = (fin - ini).days
        if n < 0 or n > 400:
            raise ValueError("rango raro: %r" % celda)
        return [ini + dt.timedelta(days=i) for i in range(n + 1)]
    return [_fecha(t, anio=anio)]


def _num(t):
    t = (t or "").strip().replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None          # s/d u otra cosa: no se publicó


def hoja(anio):
    r = requests.get(HOJA % (KEY, GIDS[anio]), timeout=90)
    r.raise_for_status()
    tabla = BeautifulSoup(r.text, "html.parser").find("table")
    filas = [[c.get_text(" ").strip() for c in tr.find_all(["td", "th"])] for tr in tabla.find_all("tr")]
    # la primera columna es el número de fila de la planilla
    return [f[1:] for f in filas if len(f) > 1]


def parsear(anio):
    filas = hoja(anio)
    cab = " ".join(" ".join(f).lower() for f in filas[:6])
    for esperado in ESPERADO:
        if esperado not in cab:
            raise ValueError("cabecera de %d distinta (falta %r)" % (anio, esperado))
    if "diversas" in cab or "agropecuaria" in cab:
        raise ValueError("%d abre la cartera general en Diversas/Agropecuaria" % anio)
    out, avisos, previo = {}, [], {}
    for f in filas:
        if not f or not re.match(r"^\d", f[0]):
            continue
        try:
            ds = dias(f[0], anio)
        except Exception as e:
            avisos.append("fecha ilegible %r (%s)" % (f[0], e))
            continue
        vals = f[1:]
        reg = {}
        for k, col in enumerate(COLUMNAS):
            v = _num(vals[2 * k]) if 2 * k < len(vals) else None
            if v is not None:
                reg[col] = v
        for d in ds:
            out[d] = reg
    # control de saltos (la planilla está en orden descendente: se recorre por fecha)
    for d in sorted(out):
        for col, v in out[d].items():
            p = previo.get(col)
            if p and abs(v - p) / p > 0.40:
                avisos.append("%s %s: %s → %s (salto > 40 %%)" % (d, col, p, v))
            previo[col] = v
    return out, avisos


def main():
    aplicar = "--aplicar" in sys.argv
    anios = [2025, 2026]
    if "--anios" in sys.argv:
        anios = [int(x) for x in sys.argv[sys.argv.index("--anios") + 1].split(",")]
    filas = []
    for a in anios:
        try:
            datos, avisos = parsear(a)
        except Exception as e:
            print("✗ %d SALTEADO: %s" % (a, e))
            continue
        print("%d: %d días (%s → %s)" % (a, len(datos), min(datos), max(datos)))
        for av in avisos[:8]:
            print("   ⚠", av)
        for d, reg in datos.items():
            if reg:
                filas.append({"FECHA": d.isoformat(), **reg})
    ult = max(filas, key=lambda r: r["FECHA"]) if filas else None
    print("Último día:", ult)
    if not aplicar:
        print("\nSimulacro. Para escribir: --aplicar")
        return
    from dotenv import load_dotenv
    load_dotenv(os.path.join(AQUI, "..", ".env"))
    import db
    n = db.upsert_valores_ancha_bulk("BNA_TASAS", filas, COLUMNAS)
    print("✓ BNA_TASAS: %s valores nuevos" % n)


if __name__ == "__main__":
    main()
