-- Approval gate for new signups. Existing rows (and staff rows) default to 'aprobado' so
-- nobody already using the platform is locked out; the register endpoint inserts new
-- owners as 'pendiente_datos'.
-- Estados: pendiente_datos -> pendiente_aprobacion -> aprobado | rechazado -> (reenvío) pendiente_aprobacion
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS estado_aprobacion varchar(25) NOT NULL DEFAULT 'aprobado';
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS motivo_rechazo text NOT NULL DEFAULT '';
-- Plan chosen during onboarding (planes live in the SuperAdmin DB, so no FK). Not applied until approval.
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS plan_solicitado_id bigint;

CREATE TABLE IF NOT EXISTS comercio_documentos (
    id             bigserial    PRIMARY KEY,
    usuario_id     bigint       NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    tipo           varchar(30)  NOT NULL,
    nombre_archivo varchar(200) NOT NULL,
    content_type   varchar(100) NOT NULL,
    tamano         integer      NOT NULL,
    contenido      bytea        NOT NULL,
    created_at     timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_comercio_documentos_usuario ON comercio_documentos (usuario_id);
