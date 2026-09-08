# -*- coding: utf-8 -*-
"""SOLO LEE. Corre todas las fuentes y dice cual anda y cual no.

    py chequear_fuentes.py

⚠ NO ESCRIBE NADA. Existe porque el README decia «UOCRA: sin scraper» cuando el
scraper existe y hasta tiene OCR, y decia «RIPTE: automatico» cuando perdia los
dos meses mas nuevos. Un estado escrito a mano se desactualiza; este se corre.

Para cada fuente informa: si contesta, cuantas filas trae, cual es el dato mas
nuevo, y —lo que mas importa— cuanto ATRASO tiene contra lo que ya esta en la
base. Una fuente que anda pero devuelve lo mismo de hace tres meses no esta
«bien»: esta muerta y no se nota.
"""
import sys
import traceback
from datetime import date
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from dotenv import load_dotenv                      # noqa: E402
load_dotenv(BASE.parent / ".env")

import db                                            # noqa: E402


def _max_fecha(fila_list, claves=("FECHA", "fecha")):
    fechas = []
    for f in fila_list or []:
        if isinstance(f, dict):
            for k in claves:
                if f.get(k):
                    fechas.append(str(f[k])[:10])
                    break
    return max(fechas) if fechas else None


def _en_base(serie):
    """Cuantos valores y cual es el mas nuevo que ya esta guardado.

    ⚠ LA FILA VIENE COMO DICT, NO COMO TUPLA. `db._conectar()` usa un cursor
    con `dict_row`, asi que `n, ult = cur.fetchone()` desempaquetaba las
    CLAVES —«count» y «max»— en vez de los valores. Y no fallaba: la columna
    mostraba «max» y la comparacion contra esa cadena daba siempre «sin
    novedades», o sea que el chequeo decia que estaba todo bien SIEMPRE.
    Un control que no puede dar mal es peor que no tenerlo.
    """
    try:
        with db._conectar() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n, MAX(fecha)::text AS ult "
                        "FROM series_valores WHERE serie = %s", (serie,))
            fila = cur.fetchone()
            if fila is None:
                return 0, None
            if isinstance(fila, dict):
                return fila.get("n"), fila.get("ult")
            return fila[0], fila[1]
    except Exception as e:
        return None, f"({str(e)[:40]})"


# (etiqueta, serie en la base, callable que trae la serie)
def _fuentes():
    from scrapers import (argentinadatos, bcra, cauciones, dolares, icc,
                          ripte, salarios, smvm, tim, uocra)
    return [
        ("RIPTE",       "RIPTE",       ripte.fetch_serie),
        ("SMVM",        "SMVM",        smvm.fetch_serie),
        ("UOCRA",       "UOCRA",       uocra.fetch_uocra),
        ("SALARIOS",    "SALARIOS",    salarios.fetch_salarios),
        ("TIM",         "TIM",         tim.fetch_tim),
        ("RIESGO_PAIS", "RIESGO_PAIS", argentinadatos.fetch_riesgo_pais),
        ("CER",         "CER",         bcra.fetch_cer),
        ("UVA",         "UVA",         bcra.fetch_uva),
        ("UVI",         "UVI",         bcra.fetch_uvi),
        ("ICL",         "ICL",         bcra.fetch_icl),
        ("BADLAR",      "BADLAR",      bcra.fetch_badlar),
        ("TAMAR",       "TAMAR",       bcra.fetch_tamar),
        ("INFLACION",   "INFLACION_INDEC", bcra.fetch_inflacion_mensual),
        ("PRESTAMOS",   "PRESTAMOS_PERSONALES", bcra.fetch_prestamos_personales),
        ("DEPOSITOS",   "DEPOSITOS_30D", bcra.fetch_depositos_30d),
        ("ADELANTOS",   "ADELANTOS_CTA_CTE", bcra.fetch_adelantos_cta_cte),
        ("BAIBAR",      "BAIBAR",      bcra.fetch_baibar),
        # ⚠ estas tres NO devuelven una serie con fechas: son la foto de HOY
        # (dolar, curva de cauciones) o un dict de series por jurisdiccion. Se
        # las marca aparte en vez de contarlas como «sin fechas legibles», que
        # se lee como un defecto y no lo es.
        ("DOLAR (hoy)", "DOLAR",       dolares.fetch_actual, "foto de hoy"),
        ("CAUCION",     "CAUCION",     cauciones.curva_completa, "foto de hoy"),
        ("ICC",         "ICC_CABA",    icc.fetch_icc, "dict por jurisdiccion"),
    ]


def main():
    hoy = date.today().isoformat()
    print("=" * 78)
    print("CHEQUEO DE FUENTES · %s   (no escribe nada)" % hoy)
    print("=" * 78)
    print("%-14s %-9s %-12s %-12s %s" % ("fuente", "trae", "mas nuevo", "en la base", "estado"))
    print("-" * 78)
    problemas = []
    for entrada in _fuentes():
        etiqueta, serie, fn = entrada[0], entrada[1], entrada[2]
        forma = entrada[3] if len(entrada) > 3 else None
        n_base, ult_base = _en_base(serie)
        if fn is None:
            print("%-14s %-9s %-12s %-12s %s"
                  % (etiqueta, "-", "-", ult_base or "-",
                     "SIN FUNCION conocida en el modulo"))
            problemas.append("%s: no encontre la funcion que trae la serie" % etiqueta)
            continue
        try:
            filas = fn()
            n = len(filas) if hasattr(filas, "__len__") else 0
            ult = _max_fecha(filas) or "?"
            # ⚠ el atraso contra LA BASE es el dato que importa: una fuente que
            # contesta pero no aporta nada nuevo esta muerta y no se nota.
            if forma:
                # no es una serie fechada: se informa lo que es y se sigue
                print("%-14s %-9s %-12s %-12s %s"
                      % (etiqueta, n, forma, ult_base or "-",
                         "OK — %s, no aporta fechas" % forma))
                continue
            if ult_base and ult != "?" and ult <= str(ult_base):
                estado = "sin novedades (la base ya tiene %s)" % ult_base
            elif ult != "?":
                estado = "OK — aporta hasta %s" % ult
            else:
                estado = "contesta pero sin fechas legibles"
            print("%-14s %-9s %-12s %-12s %s"
                  % (etiqueta, n, ult, ult_base or "-", estado))
            # lo que el propio scraper no pudo leer
            for attr in ("NO_LEIDAS", "_NO_LEIDAS"):
                malas = getattr(sys.modules[fn.__module__], attr, None)
                if malas:
                    print("%-14s %s" % ("", "⚠ no leidas: %s" % list(malas)[:4]))
                    problemas.append("%s: %d fila(s) ilegibles" % (etiqueta, len(malas)))
        except Exception as e:
            print("%-14s %-9s %-12s %-12s %s"
                  % (etiqueta, "ERROR", "-", ult_base or "-",
                     "%s: %s" % (type(e).__name__, str(e)[:44])))
            problemas.append("%s: %s" % (etiqueta, str(e)[:80]))
            if "-v" in sys.argv:
                traceback.print_exc()

    print("-" * 78)
    if problemas:
        print("A MIRAR (%d):" % len(problemas))
        for p in problemas:
            print("   · %s" % p)
    else:
        print("todas las fuentes contestan y aportan.")


if __name__ == "__main__":
    main()
