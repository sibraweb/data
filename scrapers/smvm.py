"""
SMVM — Salario Mínimo, Vital y Móvil.

Juan, 2026-09-08: *«junto con el RIPTE también quiero tener un historial del
mínimo vital y móvil»*.

DOS FUENTES, Y NO ES REDUNDANCIA
--------------------------------
    argentina.gob.ar/trabajo/consejodelsalario   la resolucion VIGENTE
    estudiodelamo.com/evolucion-salario-...      el HISTORICO desde 2010

La oficial publica solo el cronograma que esta rigiendo —hoy octubre,
noviembre y diciembre de 2026— y no el pasado. El historico de 16 años vive en
la tabla del estudio, que ademas trae la NORMATIVA de cada tramo
(«RESOL-2025-9-APN-CNEPYSMVYM»), que es lo que lo hace verificable.

⚠ CADA VALOR VIAJA CON SU FUENTE, y eso no es prolijidad: uno de los dos
origenes es el Estado y el otro es el blog de un estudio contable. Son datos
distintos aunque el numero coincida, y el que despues discuta un ajuste tiene
derecho a saber cual esta mirando. Por eso hay una columna `FUENTE` y no una
serie unica sin marca.

⚠ SI SE PISAN, GANA LA OFICIAL. Al 2026-09-08 no se pisan —la oficial arranca
en octubre-2026 y el historico termina en agosto-2026— pero el dia que se
solapen no puede quedar librado al orden en que se leyeron.

⚠ EL SMVM NO ES MENSUAL: cambia cuando sale una resolucion, y entre una y otra
se mantiene. La serie guarda la fecha DESDE la que rige cada valor; quien la
consulte para una fecha cualquiera tiene que tomar el ultimo valor anterior o
igual, no buscar el mes exacto.
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

URL_OFICIAL = "https://www.argentina.gob.ar/trabajo/consejodelsalario"
URL_HISTORICO = "https://estudiodelamo.com/evolucion-salario-minimo-vital-movil-argentina/"

_UA = {"User-Agent": "Mozilla/5.0"}

MESES = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
    "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
    "septiembre": "09", "setiembre": "09", "octubre": "10",
    "noviembre": "11", "diciembre": "12",
}

# lo que no se pudo leer, para que el job lo pueda decir en vez de encogerse
NO_LEIDAS: list[str] = []


def _monto(txt: str) -> float | None:
    """'$ 391.200' / '376.600 ARS' -> 391200.0"""
    t = (txt or "").replace("$", "").replace("\xa0", " ")
    t = re.sub(r"(?i)\bars\b|\bpesos\b", "", t).strip()
    t = t.replace(".", "").replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    try:
        return float(m.group(0)) if m else None
    except ValueError:
        return None


def _fecha_oficial(txt: str) -> str | None:
    """'a partir del 1/10/2026' -> '2026-10-01'"""
    m = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})", txt or "")
    if not m:
        return None
    d, mes, a = m.groups()
    return f"{a}-{int(mes):02d}-{int(d):02d}"


# El SMVM existe desde 1964, pero la serie util arranca en 2010 y nada puede
# regir mas alla del año que viene: una resolucion fija fechas cercanas.
_ANIO_MIN, _ANIO_MAX = 1964, 2100


def _fecha_larga(txt: str) -> str | None:
    """'1 de agosto de 2026' -> '2026-08-01'.

    ⚠ RECHAZA AÑOS IMPOSIBLES, Y NO LOS ARREGLA. La fuente tiene un error de
    tipeo real: dice «1 de septiembre de 2109» donde va 2019 —se ve porque
    queda entre octubre-2019 y agosto-2019, y la normativa es «Res. 6/19»—.
    Un 2109 colado en la serie se sienta primero para siempre y se lleva
    puesto cualquier «ultimo valor vigente».

    Corregirlo mirando los vecinos seria DEDUCIR, que es justo lo que un
    extractor no debe hacer: hoy acierta y el dia que el orden cambie,
    inventa. Se descarta y se DICE, con el texto crudo, para que una persona
    decida. Si Juan confirma el valor, entra como correccion escrita —igual
    que los apodos de entidades— y no como una adivinanza del parser.
    """
    m = re.search(r"(\d{1,2})\s+de\s+([A-Za-zñÑáéíóú]+)\s+de\s+(\d{4})",
                  (txt or "").strip(), re.I)
    if not m:
        return None
    d, mes, a = m.groups()
    mm = MESES.get(mes.lower())
    if not mm:
        return None
    if not (_ANIO_MIN <= int(a) <= _ANIO_MAX):
        return None
    return f"{a}-{mm}-{int(d):02d}"


def fetch_oficial() -> list[dict]:
    """El cronograma vigente, de la pagina del Consejo del Salario."""
    r = requests.get(URL_OFICIAL, timeout=30, headers=_UA)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for tabla in soup.find_all("table"):
        for tr in tabla.find_all("tr"):
            celdas = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(celdas) < 2:
                continue
            fecha = _fecha_oficial(celdas[0])
            monto = _monto(celdas[1])
            if fecha and monto:
                out.append({"FECHA": fecha, "VALOR": monto,
                            "FUENTE": "consejodelsalario",
                            "NORMATIVA": ""})
    return out


def fetch_historico() -> list[dict]:
    """La serie desde 2010, con la resolucion que fijo cada valor."""
    r = requests.get(URL_HISTORICO, timeout=40, headers=_UA)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for tabla in soup.find_all("table"):
        for tr in tabla.find_all("tr"):
            celdas = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(celdas) < 2:
                continue
            fecha = _fecha_larga(celdas[0])
            monto = _monto(celdas[1])
            if not fecha or not monto:
                if celdas[0] and celdas[0].lower() != "desde":
                    NO_LEIDAS.append(celdas[0])
                continue
            out.append({
                "FECHA": fecha, "VALOR": monto,
                "FUENTE": "estudiodelamo",
                # la normativa es lo que hace verificable un dato de tercero
                "NORMATIVA": celdas[5] if len(celdas) > 5 else "",
            })
    return out


def fetch_serie() -> list[dict]:
    """Las dos juntas, ordenadas, sin repetir fecha. Gana la oficial."""
    NO_LEIDAS.clear()
    por_fecha: dict[str, dict] = {}
    for fila in fetch_historico():
        por_fecha[fila["FECHA"]] = fila
    for fila in fetch_oficial():      # despues: pisa al historico si coinciden
        por_fecha[fila["FECHA"]] = fila
    return [por_fecha[f] for f in sorted(por_fecha, reverse=True)]


if __name__ == "__main__":
    serie = fetch_serie()
    print(f"SMVM: {len(serie)} tramos")
    if NO_LEIDAS:
        print(f"  filas que no se pudieron leer: {NO_LEIDAS[:6]}")
    for f in serie[:6]:
        print(f"   {f['FECHA']}  ${f['VALOR']:>12,.0f}  {f['FUENTE']:<20} {f['NORMATIVA']}")
    if serie:
        print("   ...")
        for f in serie[-3:]:
            print(f"   {f['FECHA']}  ${f['VALOR']:>12,.0f}  {f['FUENTE']:<20} {f['NORMATIVA']}")
