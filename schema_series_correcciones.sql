-- Cada vez que se PISA un valor ya cargado en `series_valores`, queda acá.
--
-- ⚠ POR QUE EXISTE. El upsert del proyecto es append-only a proposito
-- (PROCESO.md, "Upsert: agregar vs corregir"): nunca corrige un valor cargado.
-- Pero a veces la fuente demuestra que lo que tenemos esta mal — caso real del
-- 13/09/2026: la serie APYMECO se habia importado de un Excel (`CONST_2.xlsx`)
-- que traia 52 valores equivocados en 2022-2024, y el informe mensual de la
-- camara los tiene bien. Se verifico que APYMECO NO revisa su indice (cuatro
-- informes de 2020 a 2026, 73 meses solapados, 0 diferencias), asi que la
-- discrepancia era nuestra.
--
-- Corregir sin registrar romperia la trazabilidad: si un certificado se
-- liquido con el valor viejo, hay que poder ver cual era y de donde salio el
-- nuevo. Esto es lo mismo que `indec_op_revisiones` hace para INDEC.
--
-- ⚠ NO ES UN LOG DE AUDITORIA GENERAL: solo guarda correcciones DELIBERADAS de
-- valores ya cargados. Una carga normal (valor nuevo) no escribe acá.
CREATE TABLE IF NOT EXISTS series_correcciones (
    id              BIGSERIAL PRIMARY KEY,
    serie           TEXT NOT NULL,
    columna         TEXT NOT NULL,
    fecha           DATE NOT NULL,
    valor_anterior  NUMERIC,
    valor_nuevo     NUMERIC,
    fuente          TEXT NOT NULL,   -- que documento probo que el viejo estaba mal
    motivo          TEXT,
    corregido_el    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_series_correcciones_serie
    ON series_correcciones (serie, fecha);
