# -*- coding: utf-8 -*-
"""Tasas de MAV (Mercado Argentino de Valores) — cheques/echeqs avalados y
pagarés bursátiles, por rango de plazo y segmento.

API pública mavdata.mav-sa.com.ar (descubierta 2026-07-28, sin auth —
portada de `Vinculacion bancos/servicio/financiamiento.py`). Da tasa
promedio ponderada TNA/TEA/TEM por rango de plazo (0-30/31-60/61-90/91-120)
y segmento (avalado/garantizado/no garantizado). Es una FOTO del día —
se persiste en mercado_tasas_mav, que se PISA entera en cada refresh
(mismo patrón que brokers_tenencias / mercado_curva_cauciones).
"""
from __future__ import annotations

import datetime as dt

import requests
import urllib3

urllib3.disable_warnings()

URL = "https://mavdata.mav-sa.com.ar/api/segregacion-rangos-segmentos"


def tasas_instrumento(instrumento: str, moneda: str = "$") -> list[dict]:
    """[{instrumento, moneda, segmento, rango, tna, tea, tem, monto}]. []
    si MAV no responde para este instrumento."""
    try:
        r = requests.get(URL, params={"instrumento": instrumento, "moneda": moneda,
                                       "fecha": dt.date.today().isoformat()},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=25, verify=False)
        data = r.json()
    except Exception:
        return []
    out = []
    for seg in data.get("resultados", []):
        segmento = seg.get("segmento")
        for x in seg.get("datos", []):
            out.append({
                "instrumento": instrumento, "moneda": moneda, "segmento": segmento,
                "rango": x.get("rango"), "tna": x.get("tasa_prom_pond"),
                "tea": x.get("tasa_tea_pond"), "tem": x.get("tasa_tem_pond"),
                "monto": x.get("monto"),
            })
    return out


INSTRUMENTOS = ("cheques", "pagares")


def fetch_todo() -> list[dict]:
    """Todas las filas de cheques + pagarés en pesos. [] si MAV no responde
    a ninguno (fetch_todo NO borra la tabla si viene vacío — ver server.py)."""
    out = []
    for instrumento in INSTRUMENTOS:
        out += tasas_instrumento(instrumento)
    return out


if __name__ == "__main__":
    print(fetch_todo())
