-- Soporte para la app de domiciliarios: un nuevo rol de staff "domiciliario" y una columna para
-- saber qué repartidor reclamó cada domicilio, así dos repartidores conectados a la vez no se
-- pisan entregando el mismo pedido.
-- Run on the chefcontrol database (cloud-control-backEnd's tenant DB).

-- usuarios.rol era un ENUM de Postgres (rol_usuario) limitado a admin/cocina/inventario/mesero.
-- Agregar un valor a un ENUM requiere ser dueño del tipo (no solo de la tabla), y en producción
-- el tipo lo creó un rol distinto al de la app. Se cambia la columna a texto plano: Pydantic
-- (RolStaff) ya valida los valores permitidos en la capa de la aplicación, así que el ENUM de
-- base de datos era una segunda validación redundante que además bloquea agregar roles.
ALTER TABLE usuarios ALTER COLUMN rol DROP DEFAULT;
ALTER TABLE usuarios ALTER COLUMN rol TYPE text USING rol::text;
ALTER TABLE usuarios ALTER COLUMN rol SET DEFAULT 'mesero';

ALTER TABLE domicilios ADD COLUMN IF NOT EXISTS repartidor_id bigint REFERENCES usuarios(id);
