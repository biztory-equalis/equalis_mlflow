from dataclasses import dataclass


@dataclass
class CollectorConfig:
    """
    Paths to json with
    """

    path_geojson: str
    path_tax_sector: str
    path_vastgoed: str
    path_adress: str
    path_enterprice: str

    geolocator_timeout: int = 10
