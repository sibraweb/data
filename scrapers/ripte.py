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
    """'Abril/2026' -> '2026-04-01'. Y tambien 'Junio2026', sin barra.

    ⚠ LA BARRA ES OPCIONAL PORQUE LA PAGINA NO ES CONSISTENTE. Los dos ultimos
    meses publicados venian escritos «Junio2026» y «Mayo2026», sin separador,
    mientras que de abril para atras dice «Abril/2026». El regex exigia la
    barra, asi que esas dos filas se descartaban — y como el descarte era
    silencioso (un `continue` mas abajo), la serie simplemente dejaba de
    crecer: la base quedo clavada en abril-2026 mientras la pagina ya publicaba
    junio.

    Es el peor tipo de falla: no rompe nada, solo deja de traer lo ultimo, que
    es exactamente el dato por el que uno entra a mirar.
    """
    m = re.match(r"([A-Za-zñÑ]+)\s*/?\s*(\d{4})", mes_anio.strip())
    if not m:
        return None
    mes = MESES.get(m.group(1).lower())
    if not mes:
        return None
    return f"{m.group(2)}-{mes}-01"


_NO_LEIDAS: list[str] = []


def fetch_serie() -> list[dict]:
    _NO_LEIDAS.clear()
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
            # ⚠ se DICE lo que no se pudo leer. Una fila descartada en silencio
            # es como no haberla visto nunca; si mañana cambian el formato otra
            # vez, esto tiene que aparecer en el log del job y no en la
            # pregunta «por que la serie no se actualiza».
            _NO_LEIDAS.append(celdas[0])
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
    if _NO_LEIDAS:
        print(f"  filas que no se pudieron leer: {_NO_LEIDAS}")
    if serie:
        print("más reciente:", serie[0])
