-- Subscription billing state of a comercio (run on the chefcontrol database).
-- fecha_facturacion: when the account is next billed. During a free trial it is the day the free time
--   ends; the comercio keeps the plan until then and must pay to keep it afterwards.
-- en_prueba: the plan is currently being used as a free trial (no payment yet).
-- prueba_gratis_usada: each account gets a free trial only once.
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS fecha_facturacion timestamptz;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS en_prueba boolean NOT NULL DEFAULT false;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS prueba_gratis_usada boolean NOT NULL DEFAULT false;
