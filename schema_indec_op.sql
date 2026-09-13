-- Base de índices de INDEC para redeterminación de precios de obra pública.
-- Fuente: op_icc_sipm_2016.xls (ver scrapers/indec_obra_publica.py).
-- Se carga con: py api/cargar_indec_op.py
--
-- Va aparte de `series_valores` a propósito: aquella tiene ~30 series
-- (serie, fecha, valor) y acá hay ~440 conceptos con código CPC, jerarquía y
-- origen nacional/importado. Meterlos ahí convertía la clave `serie` en un
-- texto compuesto y dejaba la pantalla de índices con 470 opciones.

CREATE TABLE IF NOT EXISTS indec_op_conceptos (
    grupo        TEXT NOT NULL,   -- ICC_MATERIALES, IPIB_APERTURA, ICC_INCISOS, ...
    codigo       TEXT NOT NULL,   -- CPC "37440-11", inciso "m)", o _SLUG si no tiene
    origen       TEXT NOT NULL DEFAULT '',  -- NACIONAL | IMPORTADO (solo IPIB)
    cuadro       TEXT NOT NULL DEFAULT '',  -- número de cuadro dentro de la hoja
    descripcion  TEXT NOT NULL,
    publicacion  TEXT NOT NULL,   -- ICC | IPIB
    clasificacion TEXT,           -- CIIU rev.3 (IPIB) o apertura leída (incisos)
    nivel        SMALLINT,        -- profundidad en el árbol (mano de obra)
    PRIMARY KEY (grupo, codigo, origen, cuadro)
);

CREATE TABLE IF NOT EXISTS indec_op_valores (
    grupo      TEXT NOT NULL,
    codigo     TEXT NOT NULL,
    origen     TEXT NOT NULL DEFAULT '',
    cuadro     TEXT NOT NULL DEFAULT '',
    periodo    DATE NOT NULL,     -- primer día del mes, como publica INDEC
    indice     NUMERIC,           -- NULL = secreto estadístico ("s"): NO se rellena
    provisorio BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (grupo, codigo, origen, cuadro, periodo)
);

CREATE INDEX IF NOT EXISTS idx_indec_op_valores_periodo
    ON indec_op_valores (periodo);

-- Histórico de revisiones: INDEC publica hasta 6 meses como provisorios y
-- después los corrige, pero el .xls es siempre la foto de HOY — la corrección
-- no queda en ningún lado. Acá se guarda cada valor tal como se leyó en cada
-- foto, y SOLO cuando difiere de la foto anterior (si no, serían 56.000 filas
-- por mes para registrar 11 cambios).
--
-- Medido el 2026-09-11 contra la foto de ene-2026 del archivo de Wayback: de
-- 427 series, por mes cambian entre 0 y 11, y son SIEMPRE las mismas — mano de
-- obra, seguro de accidentes, sereno, capataz y los incisos a) b) p) que
-- arrastran. Ni un material se corrigió nunca.
CREATE TABLE IF NOT EXISTS indec_op_revisiones (
    grupo      TEXT NOT NULL,
    codigo     TEXT NOT NULL,
    origen     TEXT NOT NULL DEFAULT '',
    cuadro     TEXT NOT NULL DEFAULT '',
    periodo    DATE NOT NULL,   -- el mes al que se refiere el índice
    foto       DATE NOT NULL,   -- cuándo se leyó esa publicación
    indice     NUMERIC,
    provisorio BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (grupo, codigo, origen, cuadro, periodo, foto)
);

CREATE INDEX IF NOT EXISTS idx_indec_op_revisiones_periodo
    ON indec_op_revisiones (periodo, foto);
