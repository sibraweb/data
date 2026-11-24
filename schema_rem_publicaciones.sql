-- Historial congelado de las últimas 5 publicaciones del REM (BCRA), para la
-- vista "Evolución de expectativas REM (últimas 5 publicaciones)".
--
-- 2026-11-24. Tabla NUEVA y aparte: no toca `rem_forecast` ni la curva
-- combinada. Una fila por relevamiento (fecha_pronostico), escrita UNA sola
-- vez (ON CONFLICT DO NOTHING) y nunca recalculada:
--   datos = insumos originales de ESE relevamiento (REM mensual, anclas
--           interanuales y el IPC real que ya se conocía a esa fecha)
--   curva = la curva mensual armada con construir_curva_mensual() de
--           api/rem_estimaciones.py (la metodología existente) sobre esos datos
-- Al entrar la sexta publicación se borra la más vieja (ver
-- api/rem_historial.py y db.guardar_rem_publicacion()).

CREATE TABLE IF NOT EXISTS rem_publicaciones (
    fecha_pronostico DATE PRIMARY KEY,
    datos JSONB NOT NULL,
    curva JSONB NOT NULL,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

alter table public.rem_publicaciones enable row level security;
drop policy if exists rem_publicaciones_auth_read on public.rem_publicaciones;
create policy rem_publicaciones_auth_read on public.rem_publicaciones
  for select to authenticated using (true);
