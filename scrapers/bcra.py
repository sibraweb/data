"""
Series públicas del BCRA — api.bcra.gob.ar (sin auth, gratis).

Variables usadas (relevadas 2026-07-13):
  30 = CER (Coeficiente de Estabilización de Referencia, base 2.2.02=1)
  31 = UVA (Unidad de Valor Adquisitivo, base 31.3.16=14.05)
   4 = Tipo de cambio minorista (oficial, promedio vendedor)
  40 = ICL (Índice para Contratos de Locación, base 30.6.20=1) — diario
   7 = BADLAR bancos privados (TNA %) — diario
  27 = Inflación mensual INDEC (dato REAL, no previsión) — mensual, ~1 mes de atraso
  32 = UVI (Unidad de Vivienda, base 31.3.16=14.05 — misma fecha de origen que UVA
       pero ajuste distinto; ya divergieron bastante: UVA≈2029 vs UVI≈1475 en jul-2026)
  11 = BAIBAR (préstamos entre entidades privadas, TNA %) — diario
  12 = Depósitos a plazo fijo 30 días (TNA %) — diario
  13 = Adelantos en cuenta corriente (TNA %) — diario
  14 = Préstamos personales (TNA %) — diario
  44 = TAMAR bancos privados (TNA %) — diario

Confirmado con "Notas Metodológicas de las tasas de interés y coeficientes de
ajuste establecidos por el BCRA" (bcra.gob.ar/archivos/Pdfs/PublicacionesEstadisticas/tasmet.pdf):
UVI se arma con el ICC de INDEC (vivienda unifamiliar modelo 6), e ICL se arma
con IPC (INDEC) + RIPTE a partes iguales — o sea que ya cubrimos sus insumos.

TIM (Tasa de Intereses Moratorios, CCC art. 768) es nueva (arrancó 08/01/2026)
y no está confirmada en este endpoint JSON — se scrapea directo del Excel
oficial en scrapers/tim.py.

id 160 (tasa de política monetaria) se probó y no devuelve datos —
el BCRA parece haber dejado de publicarla como tal.
"""

from __future__ import annotations

import datetime as dt

import requests

BASE_URL = "https://api.bcra.gob.ar/estadisticas/v4.0/monetarias"

ID_CER = 30
ID_UVA = 31
ID_OFICIAL_MINORISTA = 4
ID_ICL = 40
ID_BADLAR = 7
ID_INFLACION_MENSUAL = 27
ID_UVI = 32
ID_BAIBAR = 11
ID_DEPOSITOS_30D = 12
ID_ADELANTOS_CTA_CTE = 13
ID_PRESTAMOS_PERSONALES = 14
ID_TAMAR = 44

_LIMIT = 3000  # máximo por página que acepta la API


def _get(url: str, params: dict) -> dict:
    try:
        r = requests.get(url, params=params, timeout=20)
    except requests.exceptions.SSLError:
        # La API del BCRA a veces sirve con cadena de certificados incompleta.
        r = requests.get(url, params=params, timeout=20, verify=False)
    r.raise_for_status()
    return r.json()


def fetch_serie(id_variable: int, desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Devuelve [{"fecha": "YYYY-MM-DD", "valor": float}, ...] paginando si hace falta."""
    hasta = hasta or dt.date.today().isoformat()
    desde = desde or "2001-01-01"

    resultados: list[dict] = []
    offset = 0
    while True:
        payload = _get(
            f"{BASE_URL}/{id_variable}",
            {"desde": desde, "hasta": hasta, "limit": _LIMIT, "offset": offset},
        )
        detalle = payload["results"][0]["detalle"] if payload.get("results") else []
        resultados.extend(detalle)
        count = payload.get("metadata", {}).get("resultset", {}).get("count", len(detalle))
        offset += _LIMIT
        if offset >= count or not detalle:
            break
    return resultados


def fetch_cer(desde: str | None = None, hasta: str | None = None) -> list[dict]:
    return fetch_serie(ID_CER, desde, hasta)


def fetch_uva(desde: str | None = None, hasta: str | None = None) -> list[dict]:
    return fetch_serie(ID_UVA, desde, hasta)


def fetch_oficial_minorista(desde: str | None = None, hasta: str | None = None) -> list[dict]:
    return fetch_serie(ID_OFICIAL_MINORISTA, desde, hasta)


def fetch_icl(desde: str | None = None, hasta: str | None = None) -> list[dict]:
    return fetch_serie(ID_ICL, desde, hasta)


def fetch_badlar(desde: str | None = None, hasta: str | None = None) -> list[dict]:
    return fetch_serie(ID_BADLAR, desde, hasta)


def fetch_inflacion_mensual(desde: str | None = None, hasta: str | None = None) -> list[dict]:
    return fetch_serie(ID_INFLACION_MENSUAL, desde, hasta)


def fetch_uvi(desde: str | None = None, hasta: str | None = None) -> list[dict]:
    return fetch_serie(ID_UVI, desde, hasta)


def fetch_baibar(desde: str | None = None, hasta: str | None = None) -> list[dict]:
    return fetch_serie(ID_BAIBAR, desde, hasta)


def fetch_depositos_30d(desde: str | None = None, hasta: str | None = None) -> list[dict]:
    return fetch_serie(ID_DEPOSITOS_30D, desde, hasta)


def fetch_adelantos_cta_cte(desde: str | None = None, hasta: str | None = None) -> list[dict]:
    return fetch_serie(ID_ADELANTOS_CTA_CTE, desde, hasta)


def fetch_prestamos_personales(desde: str | None = None, hasta: str | None = None) -> list[dict]:
    return fetch_serie(ID_PRESTAMOS_PERSONALES, desde, hasta)


def fetch_tamar(desde: str | None = None, hasta: str | None = None) -> list[dict]:
    return fetch_serie(ID_TAMAR, desde, hasta)


if __name__ == "__main__":
    cer = fetch_cer(desde="2026-06-01")
    print(f"CER: {len(cer)} registros, último: {cer[-1] if cer else None}")
    uva = fetch_uva(desde="2026-06-01")
    print(f"UVA: {len(uva)} registros, último: {uva[-1] if uva else None}")
    icl = fetch_icl(desde="2026-06-01")
    print(f"ICL: {len(icl)} registros, último: {icl[-1] if icl else None}")
    badlar = fetch_badlar(desde="2026-06-01")
    print(f"BADLAR: {len(badlar)} registros, último: {badlar[-1] if badlar else None}")
    infl = fetch_inflacion_mensual(desde="2026-01-01")
    print(f"Inflación mensual: {len(infl)} registros, último: {infl[-1] if infl else None}")
    uvi = fetch_uvi(desde="2026-06-01")
    print(f"UVI: {len(uvi)} registros, último: {uvi[-1] if uvi else None}")
