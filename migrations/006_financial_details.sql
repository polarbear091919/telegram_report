-- Extend existing research summaries; collection/tagging tables are unchanged.
BEGIN;
ALTER TABLE report_summaries
  ADD COLUMN IF NOT EXISTS financial_details jsonb,
  ADD COLUMN IF NOT EXISTS comparison_details jsonb;
NOTIFY pgrst, 'reload schema';
COMMIT;
