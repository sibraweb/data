"""
Cotización de dólares en vivo — dolarapi.com (sin auth, gratis).

Solo da el valor ACTUAL (no serie histórica). El histórico se arma
día a día vía el scheduler, que llama fetch_actual() y lo suma a la
hoja DOLAR con upsert_series (no duplica si ya se guardó hoy).
"""

from __future__ import annotations

import requests

URL = "https://dolarapi.com/v1/dolares"

# nombre "casa" que devuelve la API -> columna en nuestra hoja DOLAR
CASAS = {
    "oficial": "OFICIAL",
    "blue": "BLUE",
    "bolsa": "MEP",
    "contadoconliqui": "CCL",
    "mayorista": "MAYORISTA",
    "cripto": "CRIPTO",
    "tarjeta": "TARJETA",
}


def fetch_actual() -> dict:
    r = requests.get(URL, timeout=15)
    r.raise_for_status()
    data = r.json()

    fila: dict = {}
    fecha = None
    for item in data:
        casa = item.get("casa")
        col = CASAS.get(casa)
        if not col:
            continue
        fila[f"{col}_COMPRA"] = item.get("compra")
        fila[f"{col}_VENTA"] = item.get("venta")
        fecha = fecha or (item.get("fechaActualizacion") or "")[:10]

    fila["FECHA"] = fecha
    return fila


if __name__ == "__main__":
    print(fetch_actual())
