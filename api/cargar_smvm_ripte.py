# -*- coding: utf-8 -*-
"""Carga SMVM (nueva) y refresca RIPTE en `public.series_valores`.

    py cargar_smvm_ripte.py            # simulacion, no escribe
    py cargar_smvm_ripte.py --aplicar

⚠ EL SMVM NO ES UNA SERIE MENSUAL. Cambia cuando sale una resolucion y entre
una y otra se mantiene: se guarda la fecha DESDE la que rige cada valor. Quien
lo consulte para una fecha cualquiera tiene que tomar el ultimo valor anterior
o igual — buscar el mes exacto devuelve vacio en la mayoria de los meses.

El upsert es `DO NOTHING`: lo que ya esta no se pisa. Para el SMVM alcanza
—un tramo publicado no cambia— y para RIPTE tambien, porque el INDEC no
corrige hacia atras: agrega meses.
"""
import sys
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ⚠ `db.py` LEE `os.environ` AL CONECTAR y no carga el .env por su cuenta: el
# que arranca tiene que hacerlo antes. El server lo hace; un script suelto que
# se olvida se estrella con «Falta SUPABASE_DB_URL» teniendo el archivo al lado.
from dotenv import load_dotenv                # noqa: E402
load_dotenv(BASE.parent / ".env")

import db                                     # noqa: E402
from scrapers import ripte, smvm              # noqa: E402


def _resumen(serie):
    filas = db._conectar  # solo para fallar temprano si no hay conexion
    return filas


def main():
    aplicar = "--aplicar" in sys.argv

    print("== RIPTE ==")
    r = ripte.fetch_serie()
    print("  la pagina publica %d meses (mas nuevo: %s = %s)"
          % (len(r), r[0]["FECHA"] if r else "-",
             r[0]["RIPTE"] if r else "-"))
    if getattr(ripte, "_NO_LEIDAS", None):
        print("  ⚠ filas ilegibles: %s" % ripte._NO_LEIDAS)
    filas_r = [{"FECHA": x["FECHA"], "VALOR": x["RIPTE"]} for x in r]

    print()
    print("== SMVM ==")
    s = smvm.fetch_serie()
    print("  %d tramos, de %s a %s" % (len(s), s[-1]["FECHA"] if s else "-",
                                       s[0]["FECHA"] if s else "-"))
    if smvm.NO_LEIDAS:
        # ⚠ se dice SIEMPRE, aunque no rompa nada: la fuente tiene un typo real
        # («1 de septiembre de 2109») y el dia que se sume otro hay que verlo.
        print("  ⚠ filas ilegibles (quedan AFUERA): %s" % smvm.NO_LEIDAS)
    por_fuente = {}
    for x in s:
        por_fuente[x["FUENTE"]] = por_fuente.get(x["FUENTE"], 0) + 1
    print("  por fuente: %s" % por_fuente)
    filas_s = [{"FECHA": x["FECHA"], "VALOR": x["VALOR"]} for x in s]
    for x in s[:4]:
        print("     %s  $%s  (%s)" % (x["FECHA"], x["VALOR"], x["FUENTE"]))

    if not aplicar:
        print("\n(simulacion: no se escribio nada — correr con --aplicar)")
        return

    n_r = db.upsert_valores_simple("RIPTE", filas_r)
    n_s = db.upsert_valores_simple("SMVM", filas_s)
    print("\nRIPTE: %d filas mandadas" % n_r)
    print("SMVM : %d filas mandadas" % n_s)


if __name__ == "__main__":
    main()
