-- Cierre Z automático: el comercio activa que se genere solo, a una hora fija del día, sin
-- necesidad de un clic manual. La hora que guarda este campo es la hora local de Colombia
-- (America/Bogota, UTC-5); el scheduler hace la conversión a UTC al compararla.
ALTER TABLE negocios ADD COLUMN IF NOT EXISTS cierre_automatico_activo boolean NOT NULL DEFAULT false;
ALTER TABLE negocios ADD COLUMN IF NOT EXISTS cierre_automatico_hora smallint NOT NULL DEFAULT 23;

-- Marca si un cierre lo generó el scheduler o un clic manual del comercio.
ALTER TABLE cierres_z ADD COLUMN IF NOT EXISTS automatico boolean NOT NULL DEFAULT false;
