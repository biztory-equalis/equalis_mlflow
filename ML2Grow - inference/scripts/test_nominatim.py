import sys
sys.path.insert(0, ".")

from config.collector_config import CollectorConfig
from core.enriching import DataCollecter

config = CollectorConfig(
    path_geojson="jsons/sh_statbel_statistical_sectors_31370_20250101.geojson",
    path_tax_sector="jsons/TF_PSNL_INC_TAX_SECTOR.txt",
    path_vastgoed="jsons/vastgoed_2010_9999.txt",
    path_adress="",
    path_enterprice="",
    geolocator_timeout=10,
)

dc = DataCollecter(config=config)

test_addresses = [
    "Antoon De Pesseroeylaan 50, 9831 Sint-Martens-Latem",
    "Grote Markt 1, Brussel",
]

for addr in test_addresses:
    print(f"\n--- {addr} ---")
    try:
        result = dc.enrich_data_address(addr)
        for k, v in result.items():
            print(f"  {k}: {v}")
    except Exception as e:
        print(f"  ERROR: {e!r}")
