SELECT hoofddossier_id
FROM VERWEERDER
GROUP BY hoofddossier_id
HAVING COUNT(DISTINCT verweerder_id) = 1 AND MAX(verweerder_id) != 0