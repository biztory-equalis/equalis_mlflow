from shapely.geometry import MultiPolygon, Point, Polygon, shape
from shapely.strtree import STRtree

# TODO caching on address


class SectorLocator:
    def __init__(self, geojson_data):
        # 1. Structures to store the actual geometries and link them to features
        self.polygons = []
        # Use a list to store all features/properties, indexed by the polygon's position
        self.features_by_index = []

        # 2. Iterate and flatten geometries
        for feature in geojson_data["features"]:
            geom = shape(feature["geometry"])

            # If it's a simple Polygon
            if isinstance(geom, Polygon):
                # We store the Polygon object and the feature's properties at the same index
                self.polygons.append(geom)
                self.features_by_index.append(feature)

            # If it's a MultiPolygon, we need to flatten it
            elif isinstance(geom, MultiPolygon):
                for poly in geom.geoms:
                    # Store each component polygon and the properties of its parent feature
                    self.polygons.append(poly)
                    self.features_by_index.append(feature)

            # Note: We skip unsupported geometries like Points or Lines if they exist.

        # 3. Build spatial index on all component polygons
        self.index = STRtree(self.polygons)

    def get_sector(self, point: Point) -> dict:
        """
        Queries the STRtree and correctly handles the indices returned by query().
        """

        # 1. Query the STRtree: This returns a numpy array of *indices* (numpy.int64)
        # of the polygons in self.polygons whose bounding box intersects the point.
        candidate_indices = self.index.query(point)

        # 2. Iterate through the returned indices
        for index in candidate_indices:
            # Retrieve the actual Polygon object using the index
            # This is why we created the self.polygons list.
            poly = self.polygons[index]

            # 3. Perform the expensive, accurate containment check
            if poly.contains(point):
                # 4. Use the index to retrieve the full feature/properties instantly (O(1))
                return self.features_by_index[index]

        # No feature found
        return {}

    """
    {'type': 'Feature',
    'properties': {'objectid': 9404,
    'cd_sector': '44064B032',
    'tx_sector_descr_nl': 'OUDE VIERSCHAAR',
    'tx_sector_descr_fr': 'OUDE VIERSCHAAR',
    'tx_sector_descr_de': 'OUDE VIERSCHAAR',
    'cd_sub_munty': '44064B',
    'tx_sub_munty_nl': 'DEURLE',
    'tx_sub_munty_fr': 'DEURLE',
    'tx_munty_dstr': '',
    'cd_munty_refnis': '44064',
    'tx_munty_descr_nl': 'Sint-Martens-Latem',
    'tx_munty_descr_fr': 'Sint-Martens-Latem',
    'tx_munty_descr_de': 'Sint-Martens-Latem',
    'cd_dstr_refnis': '44000',
    'tx_adm_dstr_descr_nl': 'Arrondissement Gent',
    'tx_adm_dstr_descr_fr': 'Arrondissement de Gand',
    'tx_adm_dstr_descr_de': 'Bezirk Gent',
    'cd_prov_refnis': '40000',
    'tx_prov_descr_nl': 'Provincie Oost-Vlaanderen',
    'tx_prov_descr_fr': 'Province de Flandre orientale',
    'tx_prov_descr_de': 'Provinz Ostflandern',
    'cd_rgn_refnis': '02000',
    'tx_rgn_descr_nl': 'Vlaams Gewest',
    'tx_rgn_descr_fr': 'Région flamande',
    'tx_rgn_descr_de': 'Flämische Region',
    'cd_country': 'BE',
    'cd_nuts_lvl1': 'BE2',
    'cd_nuts_lvl2': 'BE23',
    'cd_nuts_lvl3': 'BE234',
    'ms_area_ha': 42.2463894202329,
    'ms_perimeter_m': 4042.0,
    'dt_situation': '2025-01-01'},
    'geometry': {'type': 'MultiPolygon',
    'coordinates': [[[[97362.89999999851, 188636.69999999925],
        [97369.89999999851, 188618.0],
        [97387.20000000298, 188585.5],
        [97400.39999999851, 188554.3999999985],
        [97415.89999999851, 188519.1000000015],
        [97433.20000000298, 188485.0],
        [97445.89999999851, 188460.8999999985],
        [97459.10000000149, 188436.69999999925],
        [97480.0, 188407.8999999985],
        [97400.0, 188355.3999999985],
        [97394.39999999851, 188351.69999999925],
        [97381.20000000298, 188343.19999999925],
        [97365.70000000298, 188333.30000000075],
        [97317.89999999851, 188300.0],
        [97286.29999999702, 188277.6000000015],
        [97225.29999999702, 188235.69999999925],
        [97221.79999999702, 188233.19999999925],
        [97188.5, 188211.69999999925],
        [97133.89999999851, 188172.5],
        [97149.10000000149, 188172.5],
        [97247.5, 188171.1000000015],
        [97197.10000000149, 188126.30000000075],
        [97174.10000000149, 188100.0],
        [97182.70000000298, 188063.8999999985],
        [97191.79999999702, 188027.6000000015],
        [97204.5, 187993.8999999985],
        [97221.70000000298, 187962.3999999985],
        [97241.79999999702, 187916.0],
        [97251.5, 187875.30000000075],
        [97269.60000000149, 187827.1000000015],
        [97293.5, 187783.69999999925],
        [97316.60000000149, 187751.30000000075],
        [97344.5, 187708.5],
        [97359.0, 187676.5],
        [97362.0, 187636.6000000015],
        [97367.60000000149, 187606.6000000015],
        [97379.79999999702, 187562.1000000015],
        [97356.29999999702, 187552.0],
        [97353.10000000149, 187550.69999999925],
        [97335.29999999702, 187543.0],
        [97331.79999999702, 187553.69999999925],
        [97330.60000000149, 187557.30000000075],
        [97325.39999999851, 187554.6000000015],
        [97273.39999999851, 187527.19999999925],
        [97270.29999999702, 187536.6000000015],
        [97268.20000000298, 187535.80000000075],
        [97258.39999999851, 187566.80000000075],
        [97249.0, 187597.80000000075],
        [97240.20000000298, 187628.0],
        [97212.39999999851, 187683.0],
        [97181.60000000149, 187692.30000000075],
        [97150.79999999702, 187699.69999999925],
        [97108.70000000298, 187708.6000000015],
        [97071.29999999702, 187716.1000000015],
        [96992.89999999851, 187754.8999999985],
        [96990.29999999702, 187756.19999999925],
        [96989.5, 187756.80000000075],
        [96987.89999999851, 187757.80000000075],
        [96976.70000000298, 187778.69999999925],
        [96972.20000000298, 187787.3999999985],
        [96957.5, 187816.1000000015],
        [96985.5, 187810.8999999985],
        [97000.39999999851, 187808.19999999925],
        [96993.70000000298, 187830.8999999985],
        [96992.5, 187835.19999999925],
        [96980.39999999851, 187862.1000000015],
        [96964.39999999851, 187896.6000000015],
        [96948.20000000298, 187929.80000000075],
        [96935.60000000149, 187954.19999999925],
        [96900.79999999702, 188022.1000000015],
        [96889.29999999702, 188014.8999999985],
        [96882.60000000149, 188008.0],
        [96771.79999999702, 187933.6000000015],
        [96736.89999999851, 187994.5],
        [96721.0, 188022.5],
        [96699.60000000149, 188011.1000000015],
        [96697.20000000298, 188009.6000000015],
        [96635.10000000149, 187968.3999999985],
        [96616.29999999702, 187990.5],
        [96590.29999999702, 188025.80000000075],
        [96570.5, 188017.3999999985],
        [96543.70000000298, 188057.5],
        [96509.10000000149, 188103.6000000015],
        [96487.70000000298, 188138.6000000015],
        [96496.29999999702, 188150.8999999985],
        [96495.29999999702, 188155.80000000075],
        [96493.70000000298, 188163.5],
        [96520.10000000149, 188174.3999999985],
        [96554.20000000298, 188192.19999999925],
        [96586.5, 188207.3999999985],
        [96618.39999999851, 188220.69999999925],
        [96663.29999999702, 188241.69999999925],
        [96698.89999999851, 188262.19999999925],
        [96729.70000000298, 188279.5],
        [96783.10000000149, 188307.3999999985],
        [96849.79999999702, 188347.80000000075],
        [96897.10000000149, 188377.6000000015],
        [96955.10000000149, 188415.69999999925],
        [97013.10000000149, 188448.69999999925],
        [97063.89999999851, 188474.30000000075],
        [97116.29999999702, 188500.5],
        [97160.89999999851, 188527.3999999985],
        [97206.89999999851, 188547.5],
        [97259.5, 188585.1000000015],
        [97257.5, 188613.80000000075],
        [97257.20000000298, 188621.5],
        [97252.20000000298, 188647.3999999985],
        [97266.0, 188653.6000000015],
        [97293.70000000298, 188647.3999999985],
        [97301.39999999851, 188642.80000000075],
        [97305.60000000149, 188640.3999999985],
        [97315.20000000298, 188635.1000000015],
        [97362.89999999851, 188636.69999999925]]]]}}
    """
