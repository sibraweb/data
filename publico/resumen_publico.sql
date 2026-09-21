-- La pagina Datos de Interes lee la ULTIMA corrida del servidor, sin login.
--
-- `indices_resumen_publico` la escribe el scheduler del servidor todos los
-- dias, pero su policy es solo para `authenticated`. En vez de abrir la
-- tabla, se expone UNA funcion: devuelve la ultima fecha de publicacion y
-- nada mas. Son indices oficiales y publicos (CER, UVA, dolar, CAC...): no
-- hay nada que cuidar, pero tampoco hace falta regalar el historial entero.
create or replace function indices_resumen_hoy()
returns table (familia text, nombre text, valor numeric, fecha date,
               mom numeric, ytd numeric, yoy numeric, a5 numeric,
               publicado date, actualizado timestamptz)
language sql stable security definer set search_path = public as $$
  select r.familia, r.nombre, r.ultimo_valor, r.ultima_fecha,
         r.mom, r.ytd, r.yoy, r.a5, r.fecha_publicacion, r.actualizado
    from indices_resumen_publico r
   where r.fecha_publicacion = (select max(fecha_publicacion) from indices_resumen_publico)
   order by r.familia;
$$;
revoke all on function indices_resumen_hoy() from public;
grant execute on function indices_resumen_hoy() to anon, authenticated;

-- ── Las series de la construccion, mes a mes, para los graficos ──────
-- Las mismas que arma publico/generar.py: CAC, ICC Buenos Aires, jornal
-- UOCRA, acero y cemento del INDEC de obra publica, y el IPC en NIVEL
-- (IPC_NIVEL, que se recalcula solo cuando entra un mes). Una fila por
-- mes y serie, el ultimo valor del mes. La base 100 y el deflactado los
-- hace la pagina: asi el calculo esta a la vista y es uno solo.
-- ⚠ UNA FILA POR SERIE, con los meses adentro. Una fila por mes eran
-- ~1.200 filas y PostgREST corta en 1.000: se perdian UOCRA y el IPC, las
-- ultimas del orden alfabetico, sin ningun error.
drop function if exists series_construccion_mensual();
create or replace function series_construccion_mensual()
returns table (clave text, meses jsonb)
language sql stable security definer set search_path = public as $$
  with fuentes(clave, serie, columna) as (values
    ('cac_general',    'CAC',              'COSTO_CONSTRUCCION'),
    ('cac_mo',         'CAC',              'MANO_DE_OBRA'),
    ('cac_materiales', 'CAC',              'MATERIALES'),
    ('icc_general',    'ICC_BUENOS_AIRES', 'GENERAL'),
    ('icc_mo',         'ICC_BUENOS_AIRES', 'MANO_DE_OBRA'),
    ('icc_materiales', 'ICC_BUENOS_AIRES', 'MATERIALES'),
    ('uocra_oficial',  'UOCRA',            'OFICIAL'),
    ('ipc',            'IPC_NIVEL',        '_'),
    ('ripte',          'RIPTE',            'RIPTE'),        -- desde 2018-03
    ('dolar_blue',     'DOLAR',            'BLUE_VENTA')    -- diario: queda el ultimo del mes
  ),
  sv as (
    select distinct on (f.clave, date_trunc('month', v.fecha))
           f.clave, date_trunc('month', v.fecha)::date mes, v.valor
      from fuentes f join series_valores v on v.serie = f.serie and v.columna = f.columna
     where v.valor is not null and v.fecha >= date '2016-01-01'
     order by f.clave, date_trunc('month', v.fecha), v.fecha desc
  ),
  indec as (
    select case o.codigo when '41242-11' then 'acero' else 'cemento' end,
           date_trunc('month', o.periodo)::date, o.indice
      from indec_op_valores o
     where o.codigo in ('41242-11', '37440-11') and o.indice is not null
       and o.periodo >= date '2016-01-01'
  )
  , todo(clave, mes, valor) as (select * from sv union all select * from indec)
  select t.clave, jsonb_object_agg(to_char(t.mes, 'YYYY-MM'), t.valor order by t.mes)
    from todo t group by t.clave order by t.clave;
$$;
revoke all on function series_construccion_mensual() from public;
grant execute on function series_construccion_mensual() to anon, authenticated;

-- ── Mano de obra vigente: basico UOCRA y hora CAMARCO ────────────────
-- El ultimo basico de cada categoria del convenio 76/75 y el costo con
-- cargas sociales: basico x 2,1350, la «Incidencia de las Cargas
-- Sociales» del Trabajo Tecnico N 185 de CAMARCO (vigencia 1/07/2026). Es
-- el mismo coeficiente que usa PresupuestApp (presuapp_actualizar_mano_de_obra):
-- si cambia, se cambia en los dos. El sereno viene MENSUAL.
create or replace function mano_de_obra_hoy(p_coef numeric default 2.1350)
returns table (categoria text, basico numeric, no_remunerativo numeric, fecha date,
               coef numeric, con_cargas numeric, unidad text)
language sql stable security definer set search_path = public as $$
  with ult as (select max(fecha) f from series_valores where serie = 'UOCRA' and columna = 'OFICIAL'),
  b as (select v.columna, v.valor, v.fecha from series_valores v, ult
         where v.serie = 'UOCRA' and v.fecha = ult.f
           and v.columna in ('OFICIAL_ESPECIALIZADO','OFICIAL','MEDIO_OFICIAL','AYUDANTE','SERENO'))
  select b.columna, b.valor,
         (select n.valor from series_valores n where n.serie = 'UOCRA'
             and n.columna = b.columna || '_NO_REM' and n.fecha = b.fecha),
         b.fecha, p_coef, round(b.valor * p_coef, 2),
         case when b.columna = 'SERENO' then 'mes' else 'hora' end
    from b
   order by array_position(array['OFICIAL_ESPECIALIZADO','OFICIAL','MEDIO_OFICIAL','AYUDANTE','SERENO'], b.columna);
$$;
revoke all on function mano_de_obra_hoy(numeric) from public;
grant execute on function mano_de_obra_hoy(numeric) to anon, authenticated;
