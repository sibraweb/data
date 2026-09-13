"""
CAMARCO / Índice CAC — "Indicador de la Variación del Costo de un Edificio
Tipo en Capital Federal".

La fuente oficial (camarco.org.ar) tiene el reporte completo detrás de un
login de socios — solo el número del mes corriente es público.

Se usa la API pública de iKiwi.net.ar (https://ikiwi.net.ar/indice-cac/,
detrás de escena llama a `prestamos.ikiwi.net.ar/api/cacs`) — JSON limpio,
sin login, con el nivel del índice (no solo la variación %) para las 3
series (general/materiales/mano de obra), actualizado mes a mes. Se
descubrió leyendo el JS de la página (`apiCac.js`, define el endpoint).

Antes se usaba un CSV de cifrasonline.com.ar (Google Sheets público) que
también funciona pero requería parsear tríos de filas por período y tenía
un bug de la fuente (setiembre abreviado distinto) — esta API es más
simple y llega más al día. Si en el futuro este endpoint deja de andar,
volver a https://ikiwi.net.ar/indice-cac/ e inspeccionar sus JS.
"""

from __future__ import annotations

import calendar
import csv
import datetime as dt
import io
import re

import requests

API_URL = "https://prestamos.ikiwi.net.ar/api/cacs"


def _fin_de_mes(periodo_iso: str) -> str:
    """'2026-05-01' -> '2026-05-31' — mismo criterio de "fecha vigente a fin
    de mes" que el resto del proyecto (APYMECO/IPC ya lo usaban)."""
    fecha = dt.date.fromisoformat(periodo_iso)
    ultimo_dia = calendar.monthrange(fecha.year, fecha.month)[1]
    return fecha.replace(day=ultimo_dia).isoformat()


# La planilla publica de cifrasonline, que es la MISMA tabla pero con el
# asterisco de provisorio que la API de iKiwi no trae. Sale del <a> de
# https://www.cifrasonline.com.ar/indice-cac/
SHEET_PROVISORIOS = ("https://docs.google.com/spreadsheets/d/"
                     "1CGVDk9hzVZv4-YM8yH0CXP49uxjGNvrS/export?format=csv")

# La fuente abrevia setiembre sin la "p" en algunos periodos (bug propio,
# documentado arriba) — las dos formas apuntan al mismo mes.
_MESES_CORTOS = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
}


def fetch_cac_provisorios() -> list[dict]:
    """Que meses del CAC estan marcados PROVISORIOS por CAMARCO.

    ⚠ POR QUE OTRA FUENTE PARA ESTO. La API de iKiwi (la que da los valores)
    devuelve solo `period`, `general`, `materials`, `labour_force`: no tiene el
    asterisco. La planilla de cifrasonline si lo tiene, en la columna 3 de la
    fila del medio de cada trio, con la leyenda "(*) Provisorios" al pie.

    ⚠ Y POR QUE NO SE TOMAN LOS VALORES DE ACA TAMBIEN. Medido el 13/09/2026:
    la planilla trae may-26 Mano de Obra = 7.423,20 donde la API y nuestra base
    dicen 17.423,20. La serie va 16.205 -> 17.009 -> 17.423 -> 18.327, asi que
    7.423 seria -56% y despues +147%: le falta un digito. Los valores siguen
    saliendo de la API y de aca sale UNICAMENTE el flag.

    ⚠ SI LA PLANILLA NO CONTESTA NO SE INVENTA NADA: devuelve [] y el llamador
    deja el flag en NULL (no sabemos), que no es lo mismo que definitivo.

    Juan, 13/09/2026: creia que solo el ultimo mes era provisorio. Son varios
    —al 13/09 estaban may, jun y jul-26— y su captura del 21/08 marcaba cuatro
    (abr a jul): abr-26 cerro entre esas dos fechas. Es una ventana movil como
    la de INDEC, mas corta (3-4 meses contra 6).
    """
    r = requests.get(SHEET_PROVISORIOS, timeout=40,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    texto = r.content.decode("utf-8", "replace")

    filas = []
    for linea in csv.reader(io.StringIO(texto)):
        # la etiqueta del periodo y el asterisco viven en la fila del MEDIO de
        # cada trio (la de "Materiales"), en las columnas 1 y 2
        if len(linea) < 3:
            continue
        etiqueta = (linea[1] or "").strip().lower()
        # ⚠ 3 O 4 LETRAS. La fuente escribe setiembre como "sept-25" y el
        # resto con tres ("jul-26"): exigiendo tres exactas se perdian los 15
        # septiembres de la serie —uno por anio— y quedaban sin flag. Que
        # queden en NULL no rompe nada, pero son 15 meses en los que no se
        # puede decir si el valor cerro.
        m = re.fullmatch(r"([a-z]{3,4})-(\d{2})", etiqueta)
        if not m:
            continue
        mes = _MESES_CORTOS.get(m.group(1)[:3])
        if not mes:
            continue
        anio = 2000 + int(m.group(2))
        filas.append({
            "FECHA": _fin_de_mes(f"{anio:04d}-{mes:02d}-01"),
            "PROVISORIO": "*" in (linea[2] or ""),
        })
    return sorted(filas, key=lambda f: f["FECHA"])


def fetch_cac() -> list[dict]:
    """Devuelve una fila por período: {FECHA, COSTO_CONSTRUCCION, MATERIALES, MANO_DE_OBRA}
    (índice base 100 = dic-2014)."""
    r = requests.get(API_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    datos = r.json()

    filas = []
    for fila in datos:
        if not fila.get("period"):
            continue
        filas.append({
            "FECHA": _fin_de_mes(fila["period"]),
            "COSTO_CONSTRUCCION": fila.get("general"),
            "MATERIALES": fila.get("materials"),
            "MANO_DE_OBRA": fila.get("labour_force"),
        })

    return sorted(filas, key=lambda r: r["FECHA"])


if __name__ == "__main__":
    serie = fetch_cac()
    print(f"CAC: {len(serie)} períodos, último: {serie[-1] if serie else None}")
