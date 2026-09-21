SELECT 
    hoofddossier_id, 
    verweerder,
    verweerder_id,
    verweerder_b2b_b2c,
    verweerder_leeftijd,
    verweerder_leeftijdscategorie,
    gevangenis_key,
    verweerder_postcode,
    verweerder_straat,
    verweerder_straat_clean,
    verweerder_nr,
    verweerder_adres,
    verweerder_gemeente,
    verweerder_provincie,
    verweerder_gewest,
FROM VERWEERDER
WHERE verweerder_id IN ({verweerder_id_filter})