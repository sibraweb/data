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
