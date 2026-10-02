-- Cómo se cobra el domicilio de cada negocio: gratis, un valor personalizado o automático por distancia
-- (tarifa base + valor por km adicional, al estilo Rappi / iFood). Run on the chefcontrol database.
CREATE TABLE IF NOT EXISTS domicilio_config (
    usuario_id bigint PRIMARY KEY REFERENCES usuarios(id) ON DELETE CASCADE,
    modo varchar(20) NOT NULL DEFAULT 'personalizado' CHECK (modo IN ('gratis', 'personalizado', 'automatico')),
    valor_fijo numeric(12, 2),
    tarifa_base numeric(12, 2) NOT NULL DEFAULT 0,
    km_base numeric(6, 2) NOT NULL DEFAULT 2,
    valor_km numeric(12, 2) NOT NULL DEFAULT 0,
    radio_max_km numeric(6, 2),
    lat double precision,
    lng double precision,
    updated_at timestamptz NOT NULL DEFAULT now()
);
