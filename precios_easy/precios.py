# -*- coding: utf-8 -*-
"""Precios de mercado: UN comando para los catálogos, lo vinculado y los vínculos.

Juan, 2026-10-12: «vamos a unificar los jobs de precios». Los tres niveles del
circuito de mercado (Bercomat, Easy, MercadoLibre) viven acá:

  catalogo [easy|bercomat|todo]     baja el catálogo COMPLETO a CSV en Drive
                                    (precios_easy.py / precios_bercomat.py). Pesado:
                                    una vez por mes alcanza.
  vinculados [--aplicar] [--solo easy|bercomat]
                                    refresca el precio de lo que YA está vinculado a un
                                    insumo Sibratech y deja una cotización si cambió
                                    (actualizar_vinculados.py). Liviano: semanal.
  vincular <vinculos/x.json> [--aplicar]
                                    graba vínculos nuevos + su cotización
                                    (vincular_precios.py), con la marca/línea elegida.

MercadoLibre NO está acá a propósito: abre un navegador con ventana (job atendido) y
se corre a pedido desde `mercadolibre/`.

El estado «INCOMPLETA» de un catálogo (unos pocos productos que el sitio no devolvió)
no es una falla: el CSV se escribió. Sólo una corrida FALLIDA devuelve error.
"""
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).parent
PY = sys.executable

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _correr(script, args=()):
    """Corre un script hermano, reenvía su salida y devuelve (código, último ESTADO)."""
    cmd = [PY, "-X", "utf8", str(AQUI / script), *args]
    print(f"▶ {script} {' '.join(args)}".rstrip(), flush=True)
    p = subprocess.Popen(cmd, cwd=str(AQUI), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    estado = ""
    for linea in p.stdout:
        print(linea.rstrip(), flush=True)
        if "ESTADO:" in linea:
            estado = linea.split("ESTADO:", 1)[1].strip()
    return p.wait(), estado


def catalogo(fuentes, extra):
    rc = 0
    for f in fuentes:
        codigo, estado = _correr(f"precios_{f}.py", extra)
        ok = codigo == 0 or estado.startswith(("COMPLETA", "INCOMPLETA", "SECA"))
        print(f"■ {f}: {'OK' if ok else 'FALLÓ'} — {estado or 'sin estado'} (código {codigo})", flush=True)
        if not ok:
            rc = 1
    return rc


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, resto = argv[1], argv[2:]
    if cmd == "catalogo":
        fuente = resto[0] if resto and not resto[0].startswith("-") else "todo"
        extra = resto[1:] if resto and not resto[0].startswith("-") else resto
        if fuente not in ("easy", "bercomat", "todo"):
            print(f"fuente desconocida: {fuente} (easy | bercomat | todo)")
            return 2
        return catalogo(["easy", "bercomat"] if fuente == "todo" else [fuente], extra)
    if cmd == "vinculados":
        codigo, _ = _correr("actualizar_vinculados.py", resto)
        return codigo
    if cmd == "vincular":
        codigo, _ = _correr("vincular_precios.py", resto)
        return codigo
    print(f"comando desconocido: {cmd}\n")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
