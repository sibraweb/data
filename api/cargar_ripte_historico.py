"""RIPTE histórico (desde julio de 1994) desde la API de series de datos.gob.ar.

El scraper de todos los días (scrapers/ripte.py) lee la página de
argentina.gob.ar, que muestra sólo los últimos meses: por eso la serie
arrancaba en marzo de 2018. La serie completa está publicada en
datos.gob.ar con el id 158.1_REPTE_0_0_5 (Secretaría de Seguridad Social).

Antes de escribir se compara contra lo que ya tenemos: si algún mes en común
no coincide, no se carga nada. Sólo agrega los meses que faltan; no pisa.

    py api/cargar_ripte_historico.py            # simulacro
    py api/cargar_ripte_historico.py --aplicar
"""
import calendar, datetime, io, os, re, sys
import requests, psycopg

AQUI = os.path.dirname(os.path.abspath(__file__))
API = "https://apis.datos.gob.ar/series/api/series/?ids=158.1_REPTE_0_0_5&limit=1000&format=json"

url = re.search(r"SUPABASE_DB_URL\s*=\s*(.+)",
                io.open(os.path.join(AQUI, "..", ".env"), encoding="utf-8").read()).group(1).strip().strip("\"'")
datos = [(f, v) for f, v in requests.get(API, timeout=40).json()["data"] if v is not None]

with psycopg.connect(url) as cn:
    nuestros = {r[0].strftime("%Y-%m"): float(r[1]) for r in cn.execute(
        "select fecha, valor from series_valores where serie='RIPTE' and columna='RIPTE'")}
    comun = [(f[:7], v, nuestros[f[:7]]) for f, v in datos if f[:7] in nuestros]
    malos = [x for x in comun if abs(x[1] - x[2]) > 0.5]
    if malos:
        sys.exit(f"NO SE CARGA: {len(malos)} meses no coinciden con lo que ya tenemos, ej. {malos[:3]}")
    faltan = []
    for f, v in datos:
        if f[:7] in nuestros:
            continue
        y, m = int(f[:4]), int(f[5:7])
        # fin de mes, como las filas viejas de la serie
        faltan.append((datetime.date(y, m, calendar.monthrange(y, m)[1]), v))
    print(f"coinciden {len(comun)} meses en común; faltan {len(faltan)}"
          + (f" ({faltan[0][0]} a {faltan[-1][0]})" if faltan else ""))
    if "--aplicar" in sys.argv and faltan:
        with cn.cursor() as cur:
            cur.executemany("""insert into series_valores (serie, columna, fecha, valor)
                               values ('RIPTE', 'RIPTE', %s, %s)
                               on conflict (serie, columna, fecha) do nothing""", faltan)
        cn.commit()
        print(f"cargados {len(faltan)} meses")
