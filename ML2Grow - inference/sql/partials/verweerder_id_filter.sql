SELECT MIN(verweerder_id) AS verweerder_id
FROM VERWEERDER
GROUP BY hoofddossier_id
HAVING COUNT(DISTINCT verweerder_id) = 1 AND MIN(verweerder_id) != 0