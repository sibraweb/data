"""Imprime los datos planos que consume la página pública de Datos de Interés.

La página vive en GitHub Pages (estática): no puede consultar la base. Entonces
cada corrida de actualización IMPRIME dos archivos ya calculados, y la página
sólo los dibuja. Mismo criterio que la lista de precios, con una diferencia
importante: estos son índices oficiales y públicos — acá no hay nada que cuidar.

    indices_resumen.json      lo que hoy está pegado a mano en el HTML
    series_construccion.json  las series para las gráficas, ya deflactadas

Uso:  python publico/generar.py
"""
import sys, os, json, datetime
from decimal import Decimal
import psycopg

sys.stdout.reconfigure(encoding='utf-8')
AQUI = os.path.dirname(os.path.abspath(__file__))

# acero y cemento salen del INDEC de obra pública, del cuadro de ICC materiales
CONCEPTOS_INDEC = {
    'acero':   '41242-11',    # Acero aletado conformado, en barra
    'cemento': '37440-11',    # Cemento portland normal, en bolsa
}
SERIES = [
    ('cac_general',    'CAC',              'COSTO_CONSTRUCCION'),
    ('cac_mo',         'CAC',              'MANO_DE_OBRA'),
    ('cac_materiales', 'CAC',              'MATERIALES'),
    ('icc_general',    'ICC_BUENOS_AIRES', 'GENERAL'),
    ('icc_mo',         'ICC_BUENOS_AIRES', 'MANO_DE_OBRA'),
    ('icc_materiales', 'ICC_BUENOS_AIRES', 'MATERIALES'),
    ('uocra_oficial',  'UOCRA',            'OFICIAL'),
]

# ⚠ INFLACION_INDEC guarda la VARIACIÓN MENSUAL en % (1,7 · 2,1 · 1,9), no el
# nivel del índice. Para deflactar hace falta el nivel, así que se encadena:
#     nivel[base] = 100 · nivel[m] = nivel[m-1] × (1 + var[m]/100)
def nivel_ipc(variaciones, meses):
    nivel, acum = {}, 100.0
    for m in meses:
        v = variaciones.get(m)
        if v is None:
            nivel[m] = acum
            continue
        acum = acum * (1 + v / 100.0)
        nivel[m] = acum
    return nivel


def conectar():
    env = {}
    for f in [os.path.join(AQUI, '..', '.env'), os.path.join(AQUI, '..', '..', 'sibra-obra-repo', '.env')]:
        if os.path.exists(f):
            for ln in open(f, encoding='utf-8'):
                if '=' in ln and not ln.strip().startswith('#'):
                    k, v = ln.split('=', 1)
                    env.setdefault(k.strip(), v.strip().strip('"\''))
    return psycopg.connect(env['SUPABASE_DB_URL'], connect_timeout=30)


def mes(f):
    return f"{f.year:04d}-{f.month:02d}"


def num(v):
    return float(v) if isinstance(v, Decimal) else (float(v) if v is not None else None)


with conectar() as cn, cn.cursor() as cur:
    # ── 1) el resumen, tal como lo muestra la tabla ──────────────────
    # La tabla guarda una fila por cada publicación: nos quedamos con la
    # ÚLTIMA de cada índice, si no la página mostraría el mismo índice
    # repetido una vez por día de corrida.
    cur.execute("""select distinct on (nombre)
                          clave, familia, nombre, ultimo_valor, ultima_fecha,
                          mom, ytd, yoy, a5, actualizado
                   from indices_resumen_publico
                   order by nombre, fecha_publicacion desc""")
    resumen = [{
        'clave': r[0], 'familia': r[1], 'nombre': r[2],
        'valor': num(r[3]), 'fecha': r[4].isoformat() if r[4] else None,
        'mom': num(r[5]), 'ytd': num(r[6]), 'yoy': num(r[7]), 'a5': num(r[8]),
        'actualizado': r[9].isoformat() if hasattr(r[9], 'isoformat') else r[9],
    } for r in cur.fetchall()]

    # ── 2) las series mensuales ──────────────────────────────────────
    datos = {}
    for nombre, serie, columna in SERIES:
        cur.execute("""select fecha, valor from series_valores
                       where serie=%s and columna=%s and valor is not null
                       order by fecha""", (serie, columna))
        d = {}
        for f, v in cur.fetchall():
            d[mes(f)] = num(v)          # si hay varios en el mes, queda el último
        datos[nombre] = d

    for nombre, codigo in CONCEPTOS_INDEC.items():
        cur.execute("""select periodo, indice from indec_op_valores
                       where codigo=%s and indice is not null order by periodo""", (codigo,))
        datos[nombre] = {mes(f): num(v) for f, v in cur.fetchall()}

    cur.execute("""select codigo, descripcion from indec_op_conceptos where codigo = any(%s)""",
                (list(CONCEPTOS_INDEC.values()),))
    etiquetas_indec = {c: d for c, d in cur.fetchall()}

    cur.execute("""select fecha, valor from series_valores
                   where serie='INFLACION_INDEC' and columna='_' and valor is not null
                   order by fecha""")   # la columna, siempre: una serie puede tener mas de una
    ipc_var = {mes(f): num(v) for f, v in cur.fetchall()}

# ── 3) base común y deflactado por IPC ───────────────────────────────
# Se toma el primer mes en que TODAS las series tienen dato, así las curvas
# arrancan juntas y se pueden comparar de verdad.
comunes = None
for d in datos.values():
    s = set(d)
    comunes = s if comunes is None else (comunes & s)
base = min(comunes) if comunes else None
# el eje va del mes base hasta el último dato de CUALQUIER serie: las que
# todavía no publicaron su mes quedan en null y la curva simplemente corta
fin = max(max(d) for d in datos.values() if d)
meses = []
a, b_ = base.split('-') if base else ('2016', '01')
y, m_ = int(a), int(b_)
while f"{y:04d}-{m_:02d}" <= fin:
    meses.append(f"{y:04d}-{m_:02d}")
    m_ += 1
    if m_ > 12:
        m_, y = 1, y + 1

ipc = nivel_ipc(ipc_var, meses)
salida = {'base': base, 'meses': meses, 'series': {},
          'generado': datetime.datetime.now().isoformat(timespec='seconds')}
for nombre, d in datos.items():
    if not base or base not in d:
        continue
    b = d[base]
    nominal = [round(d[m] / b * 100, 2) if m in d and b else None for m in meses]
    # real = nominal deflactado por el IPC encadenado, mismo mes base
    real = [round((d[m] / b) / (ipc[m] / ipc[base]) * 100, 2)
            if (m in d and m in ipc and b and ipc.get(base)) else None for m in meses]
    salida['series'][nombre] = {'nominal': nominal, 'real': real}
salida['series']['ipc'] = {
    'nominal': [round(ipc[m] / ipc[base] * 100, 2) if m in ipc else None for m in meses],
    'real': [100.0 for _ in meses],
}

salida['etiquetas'] = {
    'cac_general': 'Costo de construcción (CAC)',
    'cac_mo': 'Mano de obra (CAC)',
    'cac_materiales': 'Materiales (CAC)',
    'icc_general': 'ICC Buenos Aires general',
    'icc_mo': 'ICC mano de obra',
    'icc_materiales': 'ICC materiales',
    'uocra_oficial': 'Jornal oficial UOCRA',
    'ipc': 'IPC (INDEC)',
    'acero': etiquetas_indec.get(CONCEPTOS_INDEC['acero'], 'Acero'),
    'cemento': etiquetas_indec.get(CONCEPTOS_INDEC['cemento'], 'Cemento'),
}

# Se escriben aca y TAMBIEN dentro de la pagina publica, que es la que los
# lee. Antes solo quedaban aca y la pagina seguia con los numeros pegados a
# mano del 19/07: el generador corria y nadie se enteraba.
# Para que salgan online falta el push del repo Pagina_principal (GitHub Pages).
PAGINA = os.path.join(AQUI, '..', '..', 'Pagina_principal', 'unidades-de-negocio',
                      'sibratech-constructora', 'datos', 'data')
for destino in [AQUI] + ([PAGINA] if os.path.isdir(os.path.dirname(PAGINA)) else []):
    os.makedirs(destino, exist_ok=True)
    json.dump(resumen, open(os.path.join(destino, 'indices_resumen.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    json.dump(salida, open(os.path.join(destino, 'series_construccion.json'), 'w', encoding='utf-8'),
              ensure_ascii=False)

print(f"indices_resumen.json      {len(resumen)} índices")
print(f"series_construccion.json  {len(salida['series'])} series · {len(meses)} meses · base {base} → {meses[-1] if meses else '—'}")
for n, s in salida['series'].items():
    # la última con dato: no todas las series publican el mismo mes
    con_dato = [(m, a, b) for m, a, b in zip(meses, s['nominal'], s['real']) if a is not None]
    if not con_dato:
        print(f"   {salida['etiquetas'].get(n, n)[:38]:<40} sin datos")
        continue
    m, a, b = con_dato[-1]
    print(f"   {salida['etiquetas'].get(n, n)[:38]:<40} {m}   nominal {a:>9,.0f}   real {b:>8,.1f}")
