-- Módulo de Nómina: perfil de pago por empleado, periodos de nómina y su liquidación detallada.
-- Run on the chefcontrol database (cloud-control-backEnd's tenant DB).

CREATE TABLE IF NOT EXISTS nomina_empleados (
    id serial PRIMARY KEY,
    usuario_id integer NOT NULL,
    staff_id integer NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    tipo_contrato varchar(30) NOT NULL DEFAULT 'indefinido',
    tipo_pago varchar(15) NOT NULL DEFAULT 'mensual',
    salario_base numeric(12, 2) NOT NULL DEFAULT 0,
    valor_hora numeric(12, 2) NOT NULL DEFAULT 0,
    eps varchar(100) NOT NULL DEFAULT '',
    afp varchar(100) NOT NULL DEFAULT '',
    arl varchar(100) NOT NULL DEFAULT '',
    fecha_ingreso date,
    banco varchar(100) NOT NULL DEFAULT '',
    tipo_cuenta varchar(15),
    numero_cuenta varchar(50) NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (usuario_id, staff_id)
);

CREATE TABLE IF NOT EXISTS nomina_periodos (
    id serial PRIMARY KEY,
    usuario_id integer NOT NULL,
    fecha_inicio date NOT NULL,
    fecha_fin date NOT NULL,
    tipo varchar(15) NOT NULL DEFAULT 'quincenal',
    estado varchar(15) NOT NULL DEFAULT 'borrador',
    created_at timestamptz NOT NULL DEFAULT now(),
    cerrado_en timestamptz
);

CREATE TABLE IF NOT EXISTS nomina_detalle (
    id serial PRIMARY KEY,
    periodo_id integer NOT NULL REFERENCES nomina_periodos(id) ON DELETE CASCADE,
    staff_id integer NOT NULL REFERENCES usuarios(id),
    nombre_snapshot varchar(200) NOT NULL DEFAULT '',
    salario_base numeric(12, 2) NOT NULL DEFAULT 0,
    dias_trabajados numeric(5, 2) NOT NULL DEFAULT 0,
    horas_extra numeric(12, 2) NOT NULL DEFAULT 0,
    bonificaciones numeric(12, 2) NOT NULL DEFAULT 0,
    propinas numeric(12, 2) NOT NULL DEFAULT 0,
    otros_descuentos numeric(12, 2) NOT NULL DEFAULT 0,
    salud numeric(12, 2) NOT NULL DEFAULT 0,
    pension numeric(12, 2) NOT NULL DEFAULT 0,
    total_devengado numeric(12, 2) NOT NULL DEFAULT 0,
    total_deducciones numeric(12, 2) NOT NULL DEFAULT 0,
    neto_pagar numeric(12, 2) NOT NULL DEFAULT 0,
    notas text NOT NULL DEFAULT '',
    UNIQUE (periodo_id, staff_id)
);
