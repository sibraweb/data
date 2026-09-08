# -*- coding: utf-8 -*-
"""Corre TODAS las fuentes una vez y dice cuanto entro de cada una.

    py sincronizar_todo.py

Es exactamente el primer ciclo de `iniciar_scheduler()`, pero sin levantar el
server ni dejar el scheduler andando: sirve para poner la base al dia ahora.

⚠ POR QUE HACE FALTA CORRERLO A MANO. Los schedulers propios del modulo estan
APAGADOS por defecto (`SIBRA_SCHEDULERS`); el diseño dice que los dispara la
consola central del panel 8400. Si esa consola no esta corriendo —o no tiene
las fuentes de indices enganchadas— nadie refresca nada, y como todo sigue
contestando bien, no se nota: simplemente las series dejan de crecer.

⚠ UNA FUENTE QUE FALLA NO FRENA A LAS DEMAS, pero se dice cual y por que. Un
`try` que se traga el error dejaria la sincronizacion «completa» con la mitad
de las series viejas.
"""
import sys
import time
import traceback
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

import server as S                                   # noqa: E402


def main():
    solo = [a for a in sys.argv[1:] if not a.startswith("-")]
    fuentes = S.FUENTES_MANUALES
    if solo:
        fuentes = {k: v for k, v in fuentes.items() if k in solo}
        if not fuentes:
            print("no conozco esas fuentes. Hay: %s"
                  % ", ".join(S.FUENTES_MANUALES))
            return

    print("=" * 74)
    print("SINCRONIZANDO %d fuente(s)" % len(fuentes))
    print("=" * 74)
    ok, fallaron = [], []
    for nombre, fn in fuentes.items():
        t0 = time.time()
        print("\n── %s ──" % nombre)
        try:
            fn()
            ok.append(nombre)
            print("   ✓ %.1fs" % (time.time() - t0))
        except Exception as e:
            fallaron.append((nombre, "%s: %s" % (type(e).__name__, str(e)[:120])))
            print("   ✗ %s: %s" % (type(e).__name__, str(e)[:160]))
            if "-v" in sys.argv:
                traceback.print_exc()

    print("\n" + "=" * 74)
    print("OK: %d   ·   fallaron: %d" % (len(ok), len(fallaron)))
    for n, e in fallaron:
        print("   ✗ %-16s %s" % (n, e))


if __name__ == "__main__":
    main()
