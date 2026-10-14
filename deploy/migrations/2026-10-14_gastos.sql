-- Gastos del negocio (arriendo, servicios, mantenimiento, etc.), separados de Ingresos
-- (que registra compras de insumos). Disponible tanto para Restobar como para Store.
CREATE TABLE IF NOT EXISTS gastos (
    id serial PRIMARY KEY,
    usuario_id integer NOT NULL,
    concepto varchar(150) NOT NULL,
    categoria varchar(60) NOT NULL DEFAULT 'otros',
    monto numeric(12, 2) NOT NULL DEFAULT 0,
    fecha date NOT NULL,
    nota text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_gastos_usuario_id ON gastos (usuario_id);
CREATE INDEX IF NOT EXISTS idx_gastos_fecha ON gastos (fecha);
