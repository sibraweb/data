"""Escribe el IPC ACUMULADO (nivel) al lado de la variación mensual.

`INFLACION_INDEC` guarda la variación de cada mes (1,7 · 2,1 · 1,9). Para
deflactar cualquier serie hace falta el NIVEL, y encadenarlo a mano cada vez es
pedir que alguien se olvide. Como `series_valores` ya tiene el campo `columna`,
el acumulado entra como una columna más de la misma serie: nada de DDL.

    INFLACION_INDEC · columna '_'      variación mensual en %   (lo que había)
    IPC_NIVEL       · serie propia     índice acumulado          (lo que se agrega)
    ⚠ NO como columna de INFLACION_INDEC: rompe a los que leen la serie sin filtrar.

El nivel NO arranca en 100 arbitrario: se ancla al último valor oficial del IPC
publicado por INDEC y se reconstruye hacia atrás, así coincide con el índice de
verdad y se puede cruzar con cualquier fuente.

    nivel[m-1] = nivel[m] / (1 + var[m]/100)

Uso:  python publico/ipc_nivel.py            → simulacro
      python publico/ipc_nivel.py --aplicar  → escribe (upsert idempotente)
"""
import sys, os
import psycopg

sys.stdout.reconfigure(encoding='utf-8')
AQUI = os.path.dirname(os.path.abspath(__file__))
APLICAR = '--aplicar' in sys.argv


def conectar():
    env = {}
    for f in [os.path.join(AQUI, '..', '.env'), os.path.join(AQUI, '..', '..', 'sibra-obra-repo', '.env')]:
        if os.path.exists(f):
            for ln in open(f, encoding='utf-8'):
                if '=' in ln and not ln.strip().startswith('#'):
                    k, v = ln.split('=', 1)
                    env.setdefault(k.strip(), v.strip().strip('"\''))
    return psycopg.connect(env['SUPABASE_DB_URL'], connect_timeout=30)


with conectar() as cn, cn.cursor() as cur:
    cur.execute("""select fecha, valor from series_valores
                   where serie='INFLACION_INDEC' and columna='_' and valor is not null
                   order by fecha""")
    var = [(f, float(v)) for f, v in cur.fetchall()]

    # el ancla: el último nivel oficial publicado y a qué mes corresponde
    cur.execute("""select ultimo_valor, ultima_fecha from indices_resumen_publico
                   where clave like '%%ipc_nivel' order by fecha_publicacion desc limit 1""")
    ancla_valor, ancla_fecha = cur.fetchone()
    ancla_valor = float(ancla_valor)

    # los niveles oficiales que ya conocemos, para controlar la reconstrucción
    cur.execute("""select distinct ultima_fecha, ultimo_valor from indices_resumen_publico
                   where clave like '%%ipc_nivel' order by ultima_fecha""")
    oficiales = {f: float(v) for f, v in cur.fetchall()}

print(f"ancla: {ancla_fecha} = {ancla_valor:,.4f}  ·  {len(var)} variaciones mensuales")

i_ancla = next((i for i, (f, _) in enumerate(var)
                if f.year == ancla_fecha.year and f.month == ancla_fecha.month), None)
if i_ancla is None:
    print('⚠ el mes del ancla no está en la serie de variaciones')
    raise SystemExit(1)

nivel = [None] * len(var)
nivel[i_ancla] = ancla_valor
for i in range(i_ancla - 1, -1, -1):          # hacia atrás
    nivel[i] = nivel[i + 1] / (1 + var[i + 1][1] / 100.0)
for i in range(i_ancla + 1, len(var)):        # hacia adelante, si hubiera
    nivel[i] = nivel[i - 1] * (1 + var[i][1] / 100.0)

print("\ncontrol contra los niveles oficiales publicados:")
ok = True
for f, v in sorted(oficiales.items()):
    j = next((i for i, (ff, _) in enumerate(var) if ff.year == f.year and ff.month == f.month), None)
    if j is None:
        continue
    dif = abs(nivel[j] - v) / v * 100
    marca = '✓' if dif < 0.01 else '⚠'
    if dif >= 0.01:
        ok = False
    print(f"   {marca} {f}  reconstruido {nivel[j]:>14,.4f}   oficial {v:>14,.4f}   dif {dif:.4f}%")

print(f"\nprimeros: {var[0][0]} = {nivel[0]:,.4f}   ·   últimos: {var[-1][0]} = {nivel[-1]:,.4f}")

if APLICAR:
    if not ok:
        print('\n⚠ la reconstrucción no coincide con los oficiales: NO se escribe')
        raise SystemExit(1)
    with conectar() as cn, cn.cursor() as cur:
        cur.executemany("""insert into series_valores (serie, columna, fecha, valor)
                           values ('IPC_NIVEL', '_', %s, %s)
                           on conflict (serie, columna, fecha) do update set valor = excluded.valor""",
                        [(f, round(n, 6)) for (f, _), n in zip(var, nivel)])
        cn.commit()
        cur.execute("""select count(*), min(fecha), max(fecha) from series_valores
                       where serie='IPC_NIVEL'""")
        print("\n✓ escrito:", cur.fetchone())
else:
    print("\n(correr con --aplicar para escribir la columna NIVEL)")
