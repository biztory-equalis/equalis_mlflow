SELECT 
    tcbb_id, 
    cbb_id, 
    tdos_id,
    bedrag, 
    beslagen_goederen, 
    timestampneerlegging, 
    timestampwijziging 
FROM TCBB
WHERE bedrag > 0
