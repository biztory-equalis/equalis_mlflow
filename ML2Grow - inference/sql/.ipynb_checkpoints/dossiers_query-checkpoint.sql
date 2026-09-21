SELECT 
    hoofddossier_id,
    hoofddossier_flag,
    factuurbedrag,
    betaling_klant,
    bedrag,
    booking_code,
    booking_dut,
    dossier_status,
    dossier_status_code,
    solvabiliteit_dossier,
    dossier_solvabiliteit,
    creatiedatum_hoofddossier,
    datumboeking,
    creatiedatum_dossierlijn,
    gerechterlijk_minnelijk,
FROM DOSSIERS
WHERE hoofddossier_id IN ({hoofddossier_ids_filter_query}) 
-- AND solvabiliteit_dossier IS NOT NULL
AND hoofddossier_flag = 1
-- AND creatiedatum_hoofddossier >= %(date)s;
AND dossier_status_code IN ('STPOPD', 'REGLE', 'TERU', 'GESM', 'STPZ', 'GZ')