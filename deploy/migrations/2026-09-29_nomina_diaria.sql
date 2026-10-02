-- Nómina: pago por día, horario semanal por empleado, y el registro de "corte" para pagos diarios.
-- Run on the chefcontrol database (cloud-control-backEnd's tenant DB).

ALTER TABLE nomina_empleados ADD COLUMN IF NOT EXISTS valor_dia numeric(12, 2) NOT NULL DEFAULT 0;
-- horario: {"lun": {"activo": true, "horas": 8}, "mar": {...}, ..., "dom": {...}}
ALTER TABLE nomina_empleados ADD COLUMN IF NOT EXISTS horario jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS nomina_pagos_diarios (
    id serial PRIMARY KEY,
    usuario_id integer NOT NULL,
    staff_id integer NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    fecha date NOT NULL,
    monto numeric(12, 2) NOT NULL DEFAULT 0,
    notas varchar(300) NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (staff_id, fecha)
);
