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


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _rango_dias(rango):
    """'0-30' -> 0 (extremo corto, para ordenar y elegir la referencia)."""
    try:
        return int(str(rango).split("-")[0])
    except (ValueError, IndexError):
        return 10**9


def referencia_por_segmento(filas: list[dict]) -> dict:
    """De las filas YA obtenidas (fetch_todo, sin pegarle de nuevo a MAV):
    para cada segmento, la TNA del rango de plazo más corto (punta de la
    curva — mismo criterio que el plazo de 1 día en cauciones). Columnas
    tipo SEGMENTO_CORTO (ascii, sin espacios) -> valor.
    {"FECHA": "YYYY-MM-DD", "AVALADO_CORTO": .., "GARANTIZADO_CORTO": .., ...}"""
    import unicodedata

    def col(segmento):
        s = unicodedata.normalize("NFKD", str(segmento)).encode("ascii", "ignore").decode()
        return s.strip().upper().replace(" ", "_") + "_CORTO"

    mejor = {}  # segmento -> (rango_dias, tna)
    for f in filas:
        tna = _num(f.get("tna"))
        if tna is None:
            continue
        rd = _rango_dias(f.get("rango"))
        seg = f.get("segmento") or "SIN_SEGMENTO"
        if seg not in mejor or rd < mejor[seg][0]:
            mejor[seg] = (rd, tna)
    fila = {"FECHA": dt.date.today().isoformat()}
    for seg, (_, tna) in mejor.items():
        fila[col(seg)] = tna
    return fila


if __name__ == "__main__":
    print(fetch_todo())
