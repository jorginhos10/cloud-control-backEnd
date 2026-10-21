-- Recuperar la contraseña con un código de 6 dígitos enviado por SMS al teléfono de la cuenta.
-- Solo se guarda el hash del código y, tras verificarlo, el hash de un token de un solo uso para
-- cambiar la contraseña.
CREATE TABLE IF NOT EXISTS recuperaciones_clave (
    id               bigserial PRIMARY KEY,
    usuario_id       bigint NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    codigo_hash      text NOT NULL,
    intentos         integer NOT NULL DEFAULT 0,
    expira_en        timestamptz NOT NULL,
    usado_en         timestamptz,                 -- el código ya se canjeó por un token
    token_hash       text,
    token_expira_en  timestamptz,
    token_usado_en   timestamptz,                 -- el token ya cambió la contraseña
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_recup_clave_usuario ON recuperaciones_clave (usuario_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_recup_clave_token ON recuperaciones_clave (token_hash) WHERE token_hash IS NOT NULL;
