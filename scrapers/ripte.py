"""
RIPTE (Remuneración Imponible Promedio de los Trabajadores Estables).

No tiene API pública — se publica como tabla HTML mensual en
argentina.gob.ar. Se scrapea esa tabla (dato con retraso de ~1 mes,
como el resto de las publicaciones oficiales).
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

URL = "https://www.argentina.gob.ar/trabajo/seguridadsocial/ripte"

MESES = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
    "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
    "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
}


def _to_float(txt: str) -> float | None:
    txt = txt.replace("$", "").replace("\xa0", "").strip()
    txt = txt.replace(".", "").replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        return None


def _periodo_a_fecha(mes_anio: str) -> str | None:
    """'Abril/2026' -> '2026-04-01'"""
    m = re.match(r"([A-Za-zñÑ]+)\s*/\s*(\d{4})", mes_anio.strip())
    if not m:
        return None
    mes = MESES.get(m.group(1).lower())
    if not mes:
        return None
    return f"{m.group(2)}-{mes}-01"


def fetch_serie() -> list[dict]:
    r = requests.get(URL, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    tabla = soup.find("table", class_="table-responsive-poncho")
    if tabla is None:
        return []

    filas = []
    for tr in tabla.find("tbody").find_all("tr"):
        celdas = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(celdas) < 2:
            continue
        fecha = _periodo_a_fecha(celdas[0])
        monto = _to_float(celdas[1])
        if fecha is None or monto is None:
            continue
        filas.append({
            "FECHA": fecha,
            "PERIODO": celdas[0],
            "RIPTE": monto,
            "VARIACION_MENSUAL": celdas[2] if len(celdas) > 2 else "",
        })
    return filas


if __name__ == "__main__":
    serie = fetch_serie()
    print(f"RIPTE: {len(serie)} registros")
    if serie:
        print("más reciente:", serie[0])
