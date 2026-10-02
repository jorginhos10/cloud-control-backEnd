-- Per-document review: the SuperAdmin can reject individual documents with a reason,
-- so the merchant knows exactly which file to fix. Estados: pendiente | rechazado.
ALTER TABLE comercio_documentos ADD COLUMN IF NOT EXISTS estado varchar(15) NOT NULL DEFAULT 'pendiente';
ALTER TABLE comercio_documentos ADD COLUMN IF NOT EXISTS motivo_rechazo text NOT NULL DEFAULT '';
