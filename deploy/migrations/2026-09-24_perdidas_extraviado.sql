-- The loss reason "robo" is replaced by "extraviado". Existing rows are converted.
-- Run on the chefcontrol database.
ALTER TABLE perdidas DROP CONSTRAINT IF EXISTS perdidas_motivo_check;
UPDATE perdidas SET motivo = 'extraviado' WHERE motivo = 'robo';
ALTER TABLE perdidas ADD CONSTRAINT perdidas_motivo_check
  CHECK (motivo IN ('vencido', 'danado', 'extraviado', 'error_cocina', 'otro'));
