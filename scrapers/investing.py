"""
Investing.com — históricos por instrument_id (sin auth, requiere sesión
de cookies previa). Mismo mecanismo ya probado y en uso en
`Servidor y bots/signals/investing_io.py` — acá se porta solo lo necesario
para MERVAL, sin depender de ese repo (son deployables distintos).
"""

from __future__ import annotations

import time
from datetime import date

import requests

ID_MERVAL = 13376  # Índice MERVAL, Buenos Aires

_HIST_URL = "https://api.investing.com/api/financialdata/{id}/historical/chart/"
_HOME_URL = "https://es.investing.com"
_TIMEOUT = 20
_RETRY_DELAY = 3

_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is not None:
        return _session
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
        "Origin": "https://es.investing.com",
        "Referer": "https://es.investing.com/",
        "domain-id": "www",
    })
    try:
        s.get(_HOME_URL, timeout=_TIMEOUT)
    except requests.RequestException:
        pass
    _session = s
    return s


def fetch_investing(instrument_id: int, start_date: str = "2000-01-01") -> list[dict]:
    """Devuelve [{"fecha": "YYYY-MM-DD", "cierre": float}, ...]"""
    s = _get_session()
    url = _HIST_URL.format(id=instrument_id)
    params = {"period": "MAX", "startDate": start_date, "endDate": str(date.today()), "pointscount": 160}

    for attempt in range(2):
        r = s.get(url, params=params, timeout=_TIMEOUT)
        if r.status_code == 403:
            global _session
            _session = None
            s = _get_session()
            if attempt == 0:
                continue
            raise PermissionError("Investing.com bloqueó la solicitud (403).")
        if r.status_code == 429:
            time.sleep(_RETRY_DELAY)
            continue
        r.raise_for_status()
        rows = r.json().get("data", [])
        break
    else:
        raise RuntimeError(f"No se pudo obtener datos para id={instrument_id}")

    resultado = []
    for ts_ms, _open, _high, _low, close, _vol, *_ in rows:
        fecha = date.fromtimestamp(ts_ms / 1000).isoformat()
        resultado.append({"FECHA": fecha, "VALOR": close})
    resultado.sort(key=lambda r: r["FECHA"])
    return resultado


def fetch_merval(start_date: str = "2000-01-01") -> list[dict]:
    return fetch_investing(ID_MERVAL, start_date)


if __name__ == "__main__":
    serie = fetch_merval(start_date="2026-06-01")
    print(f"MERVAL: {len(serie)} registros, último: {serie[-1] if serie else None}")
