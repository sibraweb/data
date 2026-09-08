"""
Yahoo Finance — historicos de indices por simbolo, sin auth ni cookies.

Juan, 2026-09-08: *«no puede ser que no exista página que publique esto»*,
despues de que la sincronizacion fallara con «Investing.com bloqueó la
solicitud (403)» y el MERVAL quedara clavado en julio.

Tenia razon: `query1.finance.yahoo.com` publica `^MERV` completo —7.492 ruedas
desde 1996-10-08— y contesta 200 a un GET pelado. No es que el dato no existiera:
era que la unica puerta que teniamos la habian cerrado.

⚠ ESTO NO REEMPLAZA A INVESTING, LO RESPALDA. Dos fuentes para el mismo numero
no es redundancia cuando una de las dos puede bloquearte de un dia para el
otro sin avisar — que es exactamente lo que paso. `fetch_merval` de
`investing.py` sigue existiendo; el scheduler intenta primero y cae aca.

⚠ LOS NULOS SON DIAS SIN RUEDA Y SE DESCARTAN. Yahoo devuelve el calendario
completo con `close: null` en feriados y suspensiones (172 de 7.492). Guardar
un null como 0 dibujaria caidas al piso que nunca existieron.
"""

from __future__ import annotations

from datetime import datetime, timezone

import requests

_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/{simbolo}"
_UA = {"User-Agent": "Mozilla/5.0"}
_TIMEOUT = 40

SIMBOLO_MERVAL = "^MERV"


def fetch_indice(simbolo: str = SIMBOLO_MERVAL,
                 desde: str | None = None) -> list[dict]:
    """[{FECHA, VALOR}] con el cierre diario. `desde` = 'YYYY-MM-DD'."""
    p1 = 0
    if desde:
        p1 = int(datetime.strptime(desde, "%Y-%m-%d")
                 .replace(tzinfo=timezone.utc).timestamp())
    r = requests.get(_BASE.format(simbolo=simbolo), timeout=_TIMEOUT,
                     headers=_UA,
                     params={"period1": p1, "period2": 9999999999,
                             "interval": "1d"})
    r.raise_for_status()
    datos = r.json().get("chart", {}).get("result") or []
    if not datos:
        return []
    d = datos[0]
    ts = d.get("timestamp") or []
    quote = (d.get("indicators", {}).get("quote") or [{}])[0]
    cierres = quote.get("close") or []
    out = []
    for t, c in zip(ts, cierres):
        if c is None:          # feriado / rueda suspendida: no es un cero
            continue
        fecha = datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat()
        out.append({"FECHA": fecha, "VALOR": round(float(c), 2)})
    return out


def fetch_merval(desde: str | None = None) -> list[dict]:
    return fetch_indice(SIMBOLO_MERVAL, desde)


if __name__ == "__main__":
    s = fetch_merval()
    print(f"MERVAL (Yahoo): {len(s)} ruedas, de {s[0]['FECHA']} a {s[-1]['FECHA']}")
    for f in s[-4:]:
        print(f"   {f['FECHA']}  {f['VALOR']:,.2f}")
