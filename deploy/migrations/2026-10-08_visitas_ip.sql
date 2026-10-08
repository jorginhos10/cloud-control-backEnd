-- Registro de visitas al front-client (una fila por carga de la app), para que el SuperAdmin
-- pueda ver cuánta gente única (por IP) llega a la plataforma. No identifica personas, solo IP.
CREATE TABLE IF NOT EXISTS visitas_ip (
    id BIGSERIAL PRIMARY KEY,
    ip TEXT NOT NULL,
    ruta TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_visitas_ip_ip ON visitas_ip (ip);
CREATE INDEX IF NOT EXISTS idx_visitas_ip_created_at ON visitas_ip (created_at);
