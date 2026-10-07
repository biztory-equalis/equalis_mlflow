SELECT hoofddossier_id
FROM VERWEERDER
GROUP BY hoofddossier_id
HAVING COUNT(DISTINCT verweerder_id) = 1 AND MAX(verweerder_id) != 0
-- Row-count cap for local testing: keep this in sync with verweerder_id_filter.sql's
-- ORDER BY/LIMIT below, so both queries agree on the same 100 hoofddossier_ids.
-- Remove both ORDER BY/LIMIT lines to go back to pulling the full dataset.
ORDER BY hoofddossier_id