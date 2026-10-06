-- Ubicación en vivo del repartidor mientras va "en_camino", para que el cliente la vea en el
-- mapa de seguimiento público.
ALTER TABLE domicilios ADD COLUMN IF NOT EXISTS repartidor_lat DOUBLE PRECISION;
ALTER TABLE domicilios ADD COLUMN IF NOT EXISTS repartidor_lng DOUBLE PRECISION;
ALTER TABLE domicilios ADD COLUMN IF NOT EXISTS repartidor_ubicacion_at TIMESTAMPTZ;
