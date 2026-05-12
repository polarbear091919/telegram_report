-- migrations/004_review_queue_index.sql
--
-- Partial index for the review viewer's primary access pattern:
--   SELECT ... FROM reports
--    WHERE tagging_status='review_needed'
--    ORDER BY tagged_at ASC
--    LIMIT 1
--
-- The existing (tagging_status, downloaded_at) index from 002 is tuned for
-- pending fetch by the tagger; this one covers the manual review FIFO.

BEGIN;

CREATE INDEX IF NOT EXISTS ix_reports_review_needed_tagged
  ON reports(tagged_at)
  WHERE tagging_status='review_needed';

COMMIT;
