-- Verificación del teléfono por SMS (código de 4 dígitos) y registro de cada SMS enviado.

-- Cada SMS que sale de la plataforma, para las métricas de mensajería del SuperAdmin.
CREATE TABLE IF NOT EXISTS sms_envios (
    id          bigserial PRIMARY KEY,
    usuario_id  bigint REFERENCES usuarios(id) ON DELETE SET NULL,
    telefono    varchar(30) NOT NULL,
    proposito   text NOT NULL DEFAULT 'verificacion',
    estado      text NOT NULL,                 -- enviado | fallido
    proveedor   text NOT NULL DEFAULT '',
    error       text NOT NULL DEFAULT '',
    pais        varchar(2),
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sms_envios_created ON sms_envios (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sms_envios_usuario ON sms_envios (usuario_id);

-- Códigos de verificación emitidos. Solo se guarda el hash del código, nunca el código.
CREATE TABLE IF NOT EXISTS verificaciones_telefono (
    id            bigserial PRIMARY KEY,
    usuario_id    bigint NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    telefono      varchar(30) NOT NULL,
    codigo_hash   text NOT NULL,
    intentos      integer NOT NULL DEFAULT 0,
    expira_en     timestamptz NOT NULL,
    verificado_en timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_verif_tel_usuario ON verificaciones_telefono (usuario_id, created_at DESC);

-- Último teléfono (solo dígitos) que la cuenta verificó con éxito.
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS telefono_verificado varchar(30) NOT NULL DEFAULT '';
