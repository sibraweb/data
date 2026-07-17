"""
Precio de alquiler de departamentos en CABA — Buenos Aires Data (CKAN oficial),
dataset "mercado-inmobiliario".

Fuente: https://cdn.buenosaires.gob.ar/datosabiertos/datasets/instituto-de-vivienda/mercado-inmobiliario/precio-alquiler-deptos.csv
Datos por barrio/comuna/cantidad de ambientes, precio promedio de publicación
en pesos. **Ojo: fuente discontinuada — el CSV llega solo hasta agosto de
2019** (el portal la marca "actualización eventual" pero en la práctica no
se actualiza). Se usa como semilla histórica para poder armar de entrada el
ratio "alquiler ÷ salario" / "alquiler ÷ costo de construcción" que pidió
Juan; hay una fuente mejor (IDECBA, actualizada a 2025/2026) pendiente de
conseguir el archivo real (ver memoria del proyecto).

Se agrega el detalle por barrio a un promedio CABA por mes y cantidad de
ambientes (2 y 3 ambientes son las únicas categorías que trae la fuente).
"""

from __future__ import annotations

import csv
import io

import requests

URL = "https://cdn.buenosaires.gob.ar/datosabiertos/datasets/instituto-de-vivienda/mercado-inmobiliario/precio-alquiler-deptos.csv"

MESES = {
    "Ene": 1, "Feb": 2, "Mar": 3, "Abr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Ago": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dic": 12,
}

import calendar


def _fin_de_mes(anio: int, mes: int) -> str:
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    return f"{anio:04d}-{mes:02d}-{ultimo_dia:02d}"


def fetch_alquileres() -> list[dict]:
    """Devuelve una fila por mes: {FECHA, PRECIO_2_AMBIENTES, PRECIO_3_AMBIENTES,
    PROMEDIO} — promedio simple entre barrios con dato ese mes (en pesos
    corrientes de cada época, sin ajustar)."""
    r = requests.get(URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    lector = csv.DictReader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";")

    # (anio, mes) -> {"2 ambientes": [precios], "3 ambientes": [precios]}
    acumulado: dict[tuple[int, int], dict[str, list[float]]] = {}
    for fila in lector:
        precio = (fila.get("precio_prom") or "").strip()
        if not precio:
            continue
        try:
            anio = int(fila["anio"])
            mes = MESES.get(fila["mes"].strip())
            valor = float(precio)
        except (KeyError, ValueError, TypeError):
            continue
        if not mes:
            continue
        ambientes = (fila.get("ambientes") or "").strip()
        clave = (anio, mes)
        acumulado.setdefault(clave, {}).setdefault(ambientes, []).append(valor)

    filas = []
    for (anio, mes), por_ambiente in acumulado.items():
        precio_2 = por_ambiente.get("2 ambientes", [])
        precio_3 = por_ambiente.get("3 ambientes", [])
        todos = precio_2 + precio_3
        if not todos:
            continue
        fila = {"FECHA": _fin_de_mes(anio, mes), "PROMEDIO": round(sum(todos) / len(todos), 2)}
        if precio_2:
            fila["PRECIO_2_AMBIENTES"] = round(sum(precio_2) / len(precio_2), 2)
        if precio_3:
            fila["PRECIO_3_AMBIENTES"] = round(sum(precio_3) / len(precio_3), 2)
        filas.append(fila)

    return sorted(filas, key=lambda r: r["FECHA"])


if __name__ == "__main__":
    serie = fetch_alquileres()
    print(f"Alquileres CABA (Buenos Aires Data): {len(serie)} períodos, "
          f"{serie[0]['FECHA'] if serie else None} a {serie[-1]['FECHA'] if serie else None}")
    print(f"último: {serie[-1] if serie else None}")
