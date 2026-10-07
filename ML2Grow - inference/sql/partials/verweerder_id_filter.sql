SELECT MIN(verweerder_id) AS verweerder_id
FROM VERWEERDER
GROUP BY hoofddossier_id
HAVING COUNT(DISTINCT verweerder_id) = 1 AND MIN(verweerder_id) != 0
-- Row-count cap for local testing: kept in sync with hoofddossier_filter.sql's
-- ORDER BY/LIMIT above, so both queries agree on the same 100 hoofddossier_ids.
-- Remove both ORDER BY/LIMIT lines to go back to pulling the full dataset.
ORDER BY hoofddossier_id