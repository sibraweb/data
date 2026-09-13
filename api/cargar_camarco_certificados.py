# -*- coding: utf-8 -*-
"""El índice PUBLICADO de descuento de certificados de obra pública (CAMARCO).

Juan, 2026-09-11: *«los valores que tengo que ajustar son desde 2018»* — y
después *«desde enero de 2018 podemos mirar??»*. Sí: por eso existe esto.

⚠⚠ POR QUÉ ESTO EXISTE SI YA TENEMOS `descuento_certificados.py`
────────────────────────────────────────────────────────────────
Porque la reconstrucción con BCRA + spread del BNA **no llega hasta enero de
2018**. Del 01/01/2018 al 05/12/2018 la tasa base era la **Cartera General
(TACG) del Banco Nación**, que no es una serie del BCRA: no la podemos
reconstruir ni aunque supiéramos la regla. El índice publicado sí la trae.

Y además el publicado es EXACTO. La reconstrucción cierra contra él con
0,06 % a 0,13 % en ocho años (0,00 % en el régimen vigente) — muy bien para un
control cruzado, pero el número que se le muestra a una contraparte conviene
que sea el que la contraparte puede mirar.

**El reparto queda así:**
  · publicado      → la verdad, del 01/01/2018 hasta la última fecha del PDF.
  · reconstrucción → extiende más allá de esa fecha, y controla al publicado.

⚠ CAMARCO NO PIDE LOGIN PARA ESTO (relevado 2026-09-11). Lo que está detrás de
socios es la vista mensual; el archivo histórico completo se publica en la
biblioteca de medios de WordPress y se baja sin credenciales. Por eso este
módulo NO guarda usuario ni contraseña: si algún día pide login, va a fallar
bajando, no autenticando, y el mensaje lo va a decir.

⚠ EL PDF SE DESCUBRE, NO SE HARDCODEA. El nombre lleva el mes adentro
("…2018-Septiembre-2026-1.pdf") y cambia cada vez que lo republican; además
suben una copia nueva en vez de pisar la vieja (la `-1`). Se pregunta por la
API de medios y se toma la más reciente.

⚠ EL CERTIFICADO DE camarco.org.ar NO VALIDA en esta máquina — igual que el de
api.bcra.gob.ar. Va `verify=False`, como en `scrapers/bcra.py`.

Uso:
    python api/cargar_camarco_certificados.py            # baja y carga
    python api/cargar_camarco_certificados.py --archivo datos/x.pdf
    python api/cargar_camarco_certificados.py --solo-csv # parsea, no toca la base
"""
from __future__ import annotations

import argparse
import calendar
import csv
import datetime as dt
import os
import re
import sys

import requests
import urllib3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_MEDIOS = ("https://www.camarco.org.ar/wp-json/wp/v2/media"
              "?search=Tasas%20Banco%20Nacion&per_page=20&orderby=date&order=desc")
UA = {"User-Agent": "Mozilla/5.0"}

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_DATOS = os.path.join(RAIZ, "datos")
CSV_SALIDA = os.path.join(DIR_DATOS, "camarco_indice_2018_2026.csv")

# Las cuatro series que se guardan. El índice es lo que se usa para calcular;
# la TNA se guarda para poder mostrar la tabla día por día sin recalcular nada
# y para poder contrastar contra la reconstrucción.
#
# ⚠ TNM y tasa diaria NO se guardan a propósito: se derivan de la TNA con la
# fórmula del BNA, exactas. Guardar un derivado es guardarse la oportunidad de
# que un día no coincida con su origen.
SERIES = {
    "indice_grandes": "CERT_BNA_IND_GRANDES",
    "indice_mipyme":  "CERT_BNA_IND_MIPYME",
    "tna_grandes":    "CERT_BNA_TNA_GRANDES",
    "tna_mipyme":     "CERT_BNA_TNA_MIPYME",
}

COLS_CSV = ["FECHA", "tna_mipyme", "tnm_mipyme", "indice_mipyme",
            "tna_grandes", "tnm_grandes", "indice_grandes"]


# ── Descarga ────────────────────────────────────────────────────────────────

def ultimo_pdf() -> tuple[str, str]:
    """(url, fecha) del archivo histórico más reciente que publicó CAMARCO."""
    r = requests.get(API_MEDIOS, timeout=60, verify=False, headers=UA)
    r.raise_for_status()
    cands = []
    for it in r.json():
        u = it.get("source_url") or ""
        # El histórico completo, no las planillas de un mes suelto.
        if u.lower().endswith(".pdf") and "evolucion-historica" in u.lower():
            cands.append((it.get("date", ""), u))
    if not cands:
        raise RuntimeError(
            "CAMARCO no devolvió ningún PDF de 'Evolución histórica de tasas "
            "Banco Nación'. Puede que hayan cambiado el nombre o movido el "
            "archivo detrás del login: revisar "
            "https://www.camarco.org.ar/categorias_indicadores/tasas/")
    cands.sort(reverse=True)
    return cands[0][1], cands[0][0][:10]


def bajar(url: str, destino: str) -> str:
    r = requests.get(url, timeout=180, verify=False, headers=UA)
    r.raise_for_status()
    if not r.content[:4] == b"%PDF":
        raise RuntimeError("lo que bajó de %s no es un PDF (¿pide login?)" % url)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "wb") as fh:
        fh.write(r.content)
    return destino


# ── Parseo ──────────────────────────────────────────────────────────────────
# El PDF es UNA PÁGINA POR MES y, en cada página, DOS tablas (MiPyME primero,
# Grandes Inversores después). Cada tabla sale del extractor como tres bloques
# consecutivos: las fechas, después TODAS las TNA seguidas de TODAS las TNM, y
# después los índices. Por eso el parser agrupa por tipo de celda y no por
# posición: la posición depende de cómo pagine el extractor, el tipo no.

def _tipo(l: str) -> str:
    if re.fullmatch(r"\d{2}/\d{2}/\d{2}", l):
        return "F"
    if re.fullmatch(r"-?[\d.]*\d,\d+%", l):
        return "P"
    if re.fullmatch(r"[\d.]*\d,\d{4,}", l):
        return "I"
    return "x"


def _num(s: str) -> float:
    return float(s.replace(".", "").replace(",", ".").replace("%", ""))


def parsear(ruta_pdf: str) -> list[dict]:
    try:
        from pdfminer.high_level import extract_text
    except ImportError:
        raise SystemExit("falta pdfminer.six — pip install pdfminer.six")

    texto = extract_text(ruta_pdf)
    filas: dict[str, dict] = {}
    problemas = []

    for pag, p in enumerate(texto.split("\f")):
        bloques: list[list] = []
        for linea in (l.strip() for l in p.split("\n")):
            if not linea:
                continue
            k = _tipo(linea)
            # ⚠ Los rótulos ("INDICE DIARIO T.E.M.", "PERIODO") caen en medio de
            # una columna y NO la cortan: se saltean en vez de cerrar el bloque.
            if k == "x":
                continue
            if bloques and bloques[-1][0] == k:
                bloques[-1][1].append(linea)
            else:
                bloques.append([k, [linea]])

        if [k for k, _ in bloques] != list("FPIFPI"):
            problemas.append((pag, "no son dos tablas F/P/I"))
            continue

        for base in (0, 3):
            F, P, I = bloques[base][1], bloques[base + 1][1], bloques[base + 2][1]
            n = len(I)
            if len(P) != 2 * n:
                problemas.append((pag, base, "faltan porcentajes"))
                continue
            if len(F) != n:
                # ⚠ En 12 de 107 páginas el extractor pierde UNA fecha (la celda
                # queda partida por el salto de página) pero trae los 31 valores.
                # La página es un mes calendario completo, así que los días se
                # reconstruyen contando — no se descarta el mes entero.
                d, m, y = F[0].split("/")
                if n != calendar.monthrange(2000 + int(y), int(m))[1]:
                    problemas.append((pag, base, "ni las fechas ni el mes cierran"))
                    continue
                F = ["%02d/%s/%s" % (j, m, y) for j in range(1, n + 1)]
            suf = "mipyme" if base == 0 else "grandes"
            for j, f in enumerate(F):
                d, m, y = f.split("/")
                fecha = "20%s-%s-%s" % (y, m, d)
                r = filas.setdefault(fecha, {"FECHA": fecha})
                r["tna_" + suf] = _num(P[j])
                r["tnm_" + suf] = _num(P[n + j])
                r["indice_" + suf] = _num(I[j])

    salida = [filas[f] for f in sorted(filas)]
    _verificar(salida, problemas)
    return salida


def _verificar(filas: list[dict], problemas: list) -> None:
    """Se chequea ANTES de guardar, no después de que alguien note un hueco.

    Un índice acumulado con un día faltante no se ve roto: se ve como un
    coeficiente un poco más chico. Por eso el corte es duro.
    """
    if not filas:
        raise RuntimeError("el PDF no dio ninguna fila — cambió el formato")
    d0 = dt.date.fromisoformat(filas[0]["FECHA"])
    d1 = dt.date.fromisoformat(filas[-1]["FECHA"])
    esperadas = (d1 - d0).days + 1
    if len(filas) != esperadas:
        raise RuntimeError(
            "faltan %d días entre %s y %s: el índice es acumulado y un hueco "
            "lo desvía sin que se note. Páginas con problemas: %r"
            % (esperadas - len(filas), d0, d1, problemas[:5]))
    incompletas = [f["FECHA"] for f in filas if len(f) != len(COLS_CSV)]
    if incompletas:
        raise RuntimeError("%d filas incompletas, la primera %s"
                           % (len(incompletas), incompletas[0]))


def escribir_csv(filas: list[dict], ruta: str = CSV_SALIDA) -> str:
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, COLS_CSV)
        w.writeheader()
        for f in filas:
            w.writerow({c: f.get(c, "") for c in COLS_CSV})
    return ruta


# ── Carga ───────────────────────────────────────────────────────────────────

def guardar(filas: list[dict]) -> dict:
    """⚠ `upsert_valores_simple` es APPEND-ONLY (ON CONFLICT DO NOTHING): no
    corrige un valor ya cargado. Es la convención de la casa y acá está bien
    para el día a día, pero ojo con un caso real: CAMARCO ya corrigió la serie
    una vez («Nota: Con fecha 06.12.2018, se corrigen las series…»). Si vuelve
    a pasar, recargar NO va a traer la corrección — hay que borrar el rango y
    volver a cargarlo a mano.
    """
    import db
    hechas = {}
    for col, serie in SERIES.items():
        rows = [{"FECHA": f["FECHA"], "VALOR": f[col]} for f in filas if col in f]
        hechas[serie] = db.upsert_valores_simple(serie, rows)
    return hechas


# ── Sincronización (lo que corre como job) ──────────────────────────────────
# ⚠ CAMARCO NO PISA EL ARCHIVO: cada republicación es un archivo NUEVO, con URL
# nueva (por eso el sufijo "-1"). Así que "¿hay algo nuevo?" se contesta
# comparando URLs, no fechas de modificación — y se contesta con un JSON de
# 3 KB en vez de bajar los 6 MB del PDF.
#
# ⚠ EL RITMO ES DE DÍAS A SEMANAS, NO DIARIO. Relevado: 28/08/2026 y 04/09/2026.
# Pedirlo todos los días no trae nada; por eso el job corre dos veces por semana
# y aun así casi siempre termina en "no hay nada nuevo".
#
# ⚠⚠ Y NO HACE FALTA QUE SEA DIARIO, porque **el índice se publica 5 días
# CALENDARIO hacia adelante**: el archivo subido el 04/09/2026 ya traía hasta el
# 09/09. No es un error de ellos — es que la tasa se lee 5 hábiles antes, así
# que el índice de los próximos días ya está determinado y se puede publicar.
# Entre una republicación y la siguiente el dato casi nunca falta.
MARCADOR = os.path.join(DIR_DATOS, "camarco_ultima_carga.json")


def _marcador_leer() -> dict:
    try:
        import json
        with open(MARCADOR, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _marcador_escribir(d: dict) -> None:
    import json
    os.makedirs(DIR_DATOS, exist_ok=True)
    with open(MARCADOR, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=2)


def sincronizar(forzar: bool = False) -> dict:
    """Mira si CAMARCO republicó; si sí, baja, parsea y carga. Si no, no hace nada.

    Devuelve siempre un dict que dice QUÉ pasó — el job lo imprime. Un job que
    no dice si trabajó o si se salteó es un job que puede estar muerto sin que
    nadie se entere.
    """
    url, publicado = ultimo_pdf()
    prev = _marcador_leer()
    if not forzar and prev.get("url") == url:
        return {"nuevo": False, "url": url, "publicado": publicado,
                "ultimo_dia": prev.get("ultimo_dia")}

    ruta = bajar(url, os.path.join(DIR_DATOS, os.path.basename(url)))
    filas = parsear(ruta)          # corta duro si falta un día (ver _verificar)
    escribir_csv(filas)
    hechas = guardar(filas)
    marca = {"url": url, "publicado": publicado,
             "ultimo_dia": filas[-1]["FECHA"], "dias": len(filas),
             "cargado": dt.datetime.now().isoformat(timespec="seconds")}
    _marcador_escribir(marca)
    return {"nuevo": True, "series": hechas, **marca}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archivo", help="PDF local en vez de bajar el de CAMARCO")
    ap.add_argument("--solo-csv", action="store_true",
                    help="parsea y escribe el CSV, no toca la base")
    ap.add_argument("--sync", action="store_true",
                    help="como corre el job: baja SOLO si CAMARCO republicó")
    args = ap.parse_args()

    if args.sync:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(RAIZ, ".env"))
        r = sincronizar()
        print("[camarco] %s" % ("cargado hasta %s (%d días)" % (r["ultimo_dia"], r["dias"])
                                if r["nuevo"] else
                                "sin novedad — sigue vigente el de %s, con dato hasta %s"
                                % (r["publicado"], r.get("ultimo_dia"))))
        return

    if args.archivo:
        ruta = args.archivo
        print("[camarco] archivo local: %s" % ruta)
    else:
        url, fecha = ultimo_pdf()
        ruta = os.path.join(DIR_DATOS, os.path.basename(url))
        print("[camarco] publicado %s -> %s" % (fecha, url))
        bajar(url, ruta)

    filas = parsear(ruta)
    print("[camarco] %d días, %s -> %s"
          % (len(filas), filas[0]["FECHA"], filas[-1]["FECHA"]))
    print("[camarco] CSV: %s" % escribir_csv(filas))

    if args.solo_csv:
        return
    from dotenv import load_dotenv
    load_dotenv(os.path.join(RAIZ, ".env"))
    for serie, n in guardar(filas).items():
        print("[camarco] %-22s %d filas ofrecidas" % (serie, n))


if __name__ == "__main__":
    main()
