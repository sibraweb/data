-- Esquema piloto para migrar CER, DOLAR, UOCRA de Sheets a Supabase.
-- Correr una sola vez en el SQL Editor del dashboard de Supabase.
-- Ver SIBRA_SERVER/PROCESO.md (Fase 6) para el contexto completo.

CREATE TABLE IF NOT EXISTS series_valores (
    id BIGSERIAL PRIMARY KEY,
    serie TEXT NOT NULL,
    columna TEXT NOT NULL DEFAULT '_',
    fecha DATE NOT NULL,
    valor NUMERIC,
    valor_texto TEXT,
    UNIQUE (serie, columna, fecha)
);
CREATE INDEX IF NOT EXISTS idx_series_valores_serie_fecha ON series_valores (serie, fecha);

-- Tablas del esquema completo (no se usan en el piloto, pero se dejan
-- creadas de una para cuando se migren las ~22 series restantes).
CREATE TABLE IF NOT EXISTS uocra_adicionales (
    clave TEXT PRIMARY KEY,
    concepto_num TEXT,
    titulo TEXT,
    texto TEXT,
    acuerdo_ref TEXT,
    valor NUMERIC,
    unidad TEXT,
    desde DATE,
    hasta DATE
);

CREATE TABLE IF NOT EXISTS materiales_cotizaciones (
    id_proveedor TEXT NOT NULL,
    descripcion TEXT NOT NULL,
    fecha DATE NOT NULL,
    precio NUMERIC,
    PRIMARY KEY (id_proveedor, descripcion, fecha)
);

CREATE TABLE IF NOT EXISTS rem_forecast (
    tipo TEXT NOT NULL,
    fecha_pronostico DATE NOT NULL,
    periodo DATE NOT NULL,
    mediana NUMERIC,
    promedio NUMERIC,
    desvio NUMERIC,
    maximo NUMERIC,
    minimo NUMERIC,
    percentil_90 NUMERIC,
    PRIMARY KEY (tipo, fecha_pronostico, periodo)
);
