-- Los negocios nuevos (recien registrados) deben arrancar en "Automático" en vez de
-- quedar fijos en Violet Original, para que ya reciban Halloween/Navidad solos cuando
-- toque la temporada, sin que el dueño tenga que entrar a cambiarlo.
-- Run on the chefcontrol database (cloud-control-backEnd's tenant DB).
ALTER TABLE negocios ALTER COLUMN apariencia SET DEFAULT 'automatico';
