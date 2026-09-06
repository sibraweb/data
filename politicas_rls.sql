-- Lectura de los índices desde el navegador: SOLO con sesión.
--
-- 2026-09-05. Hasta hoy `series_valores` e `indices_resumen_publico` tenían
-- lectura abierta a `anon`: cualquiera con la publishable key (que va en el
-- HTML, es pública por diseño) se bajaba las series enteras. Eso venía de
-- cuando el plan era publicar el Resumen como página abierta.
--
-- Al cablear la página publicada (sibraweb.github.io/data/) contra Supabase,
-- Juan definió el criterio: si el dato vive en la base, se lee con usuario,
-- igual que Market Suite. Así que las policies pasan a `authenticated`.
--
-- CONSECUENCIA: /market/tasas/ leía `series_valores` sin login (con
-- selectAllPublic). Se cambió en el mismo movimiento para que pida sesión —
-- ver markets-repo/tasas/index.html.
--
-- QUEDA ABIERTO A PROPÓSITO: `mercado_curva_cauciones` y `mercado_tasas_mav`
-- son de Tesorería, no de Índices, y no se tocaron acá.

-- Series de índices (la base de las 9 pestañas que grafica el front)
drop policy if exists series_valores_public_read on public.series_valores;
create policy series_valores_auth_read on public.series_valores
  for select to authenticated using (true);

-- Snapshot diario del Resumen (lo escribe publicar_resumen(), server.py:845)
drop policy if exists lectura_publica on public.indices_resumen_publico;
create policy indices_resumen_auth_read on public.indices_resumen_publico
  for select to authenticated using (true);

-- REM: tenía RLS prendida y NINGUNA policy, o sea que por PostgREST no la
-- leía nadie — por eso la pestaña Proyecciones no podía funcionar desde el
-- navegador ni con login.
drop policy if exists rem_forecast_auth_read on public.rem_forecast;
create policy rem_forecast_auth_read on public.rem_forecast
  for select to authenticated using (true);

-- `uocra_adicionales` y `materiales_cotizaciones` quedan cerradas: no las lee
-- el navegador (Materiales necesita la Sheet de Obra, que sale por OAuth desde
-- api/server.py). Abrirlas cuando algo del front las precise, no antes.
