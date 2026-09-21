import json
from typing import Optional

import pandas as pd
import requests
from geopy.geocoders import Nominatim
from pyproj import Transformer
from shapely.geometry import Point, shape
from tqdm.auto import tqdm

from config.collector_config import CollectorConfig
from core.sector_locator import SectorLocator

tqdm.pandas()


###
# TODO: Future step is to integrate Graydon api
###
# Find company statistics:
#   Financial summary
#       Info url: https://anypoint.mulesoft.com/exchange/portals/graydon-holding-n-v/5cc8ad1a-2f92-447f-9c4c-a48e6560cf4f/company-api-v1.0.0/minor/1.0/console/method/%238747/
#       API call: https://anypoint.mulesoft.com/mocking/api/v1/sources/exchange/assets/5cc8ad1a-2f92-447f-9c4c-a48e6560cf4f/company-api-v1.0.0/1.0.59/m/nl/companies/302459/financials/summary?client_id=5cc8ad1a2f92447f9c9ca48e6560cf4g&client_secret=7064bba96a944z90B64Cd8025Ae30A7c
#
#   Annual accounts:
#       Info url: https://anypoint.mulesoft.com/exchange/portals/graydon-holding-n-v/5cc8ad1a-2f92-447f-9c4c-a48e6560cf4f/company-api-v1.0.0/minor/1.0/console/method/%238956/
#       API call: https://anypoint.mulesoft.com/mocking/api/v1/links/2fbfe43b-9744-4e65-8714-4ebf5f2dae6c/{countryCode}/companies/{id}/financials/annualAccounts
#
#   More info about statistics:
#   --> https://anypoint.mulesoft.com/exchange/portals/graydon-holding-n-v/5cc8ad1a-2f92-447f-9c4c-a48e6560cf4f/company-api-v1.0.0/minor/1.0/console/documentation/%238/
#
# Find company Id:
#   Info url: https://anypoint.mulesoft.com/exchange/portals/graydon-holding-n-v/5cc8ad1a-2f92-447f-9c4c-a48e6560cf4f/graydon-search-api-v1.0.0/minor/1.0/console/method/%23587/
#   API call: https://anypoint.mulesoft.com/mocking/api/v1/links/f5025379-693b-4d45-bf3e-730f2914ea99/{countryCode}/companies
###


class DataCollecter:
    def __init__(self, config=CollectorConfig):
        self.start = True
        self.config = config
        self.geolocator = Nominatim(
            user_agent="Equalis", timeout=self.config.geolocator_timeout
        )

        # Transformer from WGS84 (EPSG:4326) to Lambert72 (EPSG:31370)
        self.geotransformer = Transformer.from_crs(
            "EPSG:4326", "EPSG:31370", always_xy=True
        )

        # self.street_url = "http://loc.geopunt.be/"
        with open(self.config.path_geojson) as f:
            self.geo_js = json.load(f)

        self.sector_locator = SectorLocator(self.geo_js)

        self.df_tax = pd.read_csv(self.config.path_tax_sector, delimiter="|")
        # self.df_house = pd.read_csv(
        #     self.config.path_vastgoed, delimiter="|", encoding="latin-1"
        # )

        # NOTE: used by functions that are still in a TODO state
        # self.df_addr = pd.read_csv(self.config.path_adress)
        # self.df_enterprise = pd.read_csv(self.config.path_enterprice)

    def enrich_data_address(self, address: str) -> dict:
        try:
            coordinates = self._address_to_lambert72(address=address)
        except Exception:
            return {}

        if not coordinates:
            raise Exception(f"could not convert address {address} to coördinates")

        if coordinates["country_code"] != "be":
            return {**coordinates}

        point = Point(coordinates["X_Lambert72"], coordinates["Y_Lambert72"])
        sector_info = self.sector_locator.get_sector(point)

        value_income = self.get_income(
            sector_code=sector_info["properties"]["cd_sector"]
        )

        # NOTE not sure what this information entails
        # value_house = self.get_house_info(
        #     sector_info["properties"]["tx_munty_descr_nl"].upper()
        # )

        # NOTE: for now return unfiltered dict
        return {
            **coordinates,
            **sector_info["properties"],
            **value_income,
        }

    # using approximation based on postcode
    def enrich_data_point(self, lon: float, lat: float) -> dict:
        x_lambert72, y_lambert72 = self.geotransformer.transform(lon, lat)

        coordinates = {
            "latitude": lat,
            "longitude": lon,
            "X_Lambert72": x_lambert72,
            "Y_Lambert72": y_lambert72,
        }

        point = Point(coordinates["X_Lambert72"], coordinates["Y_Lambert72"])
        sector_info = self.sector_locator.get_sector(point)

        if not sector_info:
            return {**coordinates}

        value_income = self.get_income(
            sector_code=sector_info["properties"]["cd_sector"]
        )

        return {**coordinates, **sector_info, **value_income}

    def enrich_data_point_v2(self, df):
        df = df.copy()

        # Step 1: Vectorized coordinate transform
        df = self._add_projected_coordinates(df)

        # Step 2: Create Shapely geometry objects
        df = self._add_geometry(df)

        # Step 3: Add sector + income data (row-based, small step)
        df = self._add_sector_and_income(df)

        return df

    def _add_geometry(self, df):
        df["geometry"] = [
            Point(x, y) for x, y in zip(df["X_Lambert72"], df["Y_Lambert72"])
        ]
        return df

    def _enrich_point(self, point):
        sector_info = self.sector_locator.get_sector(point)
        if not sector_info:
            return None
        sector_code = sector_info["properties"]["cd_sector"]
        return self.get_income(sector_code)

    def _add_sector_and_income(self, df):
        enriched = df["geometry"].progress_apply(self._enrich_point)

        # drop records when getting information failed
        enriched = enriched.dropna()

        enriched = enriched.apply(pd.Series)
        return df.join(enriched)

    def _add_projected_coordinates(self, df):
        x, y = self.geotransformer.transform(
            df["longitude"].values, df["latitude"].values
        )
        df["X_Lambert72"] = x
        df["Y_Lambert72"] = y
        return df

    def _address_to_lambert72(self, address: str) -> dict:
        """
        Convert a textual address to Lambert72 coordinates.
        Returns a dictionary with WGS84 and Lambert72 coordinates.

        example outputfrom geocode:
            {'address': {'ISO3166-2-lvl4': 'BE-VLG',
                'ISO3166-2-lvl6': 'BE-VOV',
                'country': 'België / Belgique / Belgien',
                'country_code': 'be',
                'county': 'Gent',
                'house_number': '50',
                'postcode': '9831',
                'region': 'Vlaanderen',
                'road': 'Antoon De Pesseroeylaan',
                'state': 'Oost-Vlaanderen',
                'town': 'Sint-Martens-Latem',
                'village': 'Deurle'},
            'addresstype': 'building',
            'boundingbox': ['51.0025849', '51.0027334', '3.6155546', '3.6158468'],
            'class': 'building',
            'display_name': '50, Antoon De Pesseroeylaan, Deurle, Sint-Martens-Latem, '
                            'Gent, Oost-Vlaanderen, Vlaanderen, 9831, België / Belgique / '
                            'Belgien',
            'importance': 5.467078660253326e-05,
            'lat': '51.0026588',
            'licence': 'Data © OpenStreetMap contributors, ODbL 1.0. '
                        'http://osm.org/copyright',
            'lon': '3.6156886',
            'name': '',
            'osm_id': 1075351274,
            'osm_type': 'way',
            'place_id': 92003552,
            'place_rank': 30,
            'type': 'house'}
        """
        location = self.geolocator.geocode(address, addressdetails=True)
        if location is None:
            raise ValueError("Address not found: " + address)

        lat = location.latitude
        lon = location.longitude

        x_lambert72, y_lambert72 = self.geotransformer.transform(lon, lat)

        coordinates = {
            "latitude": lat,
            "longitude": lon,
            "X_Lambert72": x_lambert72,
            "Y_Lambert72": y_lambert72,
            "address": location.address,
        }

        return {**coordinates, **location.raw["address"]}

    def get_income(self, sector_code: str) -> dict:
        df_result = self.df_tax[self.df_tax["CD_SECTOR"] == sector_code].copy()
        if df_result.empty:
            return {}

        dtype_map = {
            "CD_YEAR": "Int64",
            "MS_AVG_TOT_NET_TAXABLE_INC": "float",
            "MS_TOT_NET_TAXABLE_INC": "float",
            "MS_MEDIAN_NET_TAXABLE_INC": "float",
            "MS_NBR_NON_ZERO_INC": "Int64",
            "MS_INT_QUART_DIFF": "Int64",
            "MS_INT_QUART_COEFF": "Int64",
            "MS_INT_QUART_ASSYM": "Int64",
        }

        # Ensure columns exist
        for col in dtype_map:
            if col not in df_result.columns:
                df_result[col] = None

        # Replace invalid placeholders
        df_result = df_result.replace({".": None, "": None, " ": None})

        # Cast types FIRST
        df_result = df_result.astype(dtype_map)

        # Now fill NA safely
        df_result = df_result.fillna(-1)

        # Take most recent year
        df_result = df_result.sort_values("CD_YEAR", ascending=False)

        return df_result.iloc[0].to_dict()

    # NOTE what does this information represent?
    def get_house_info(self, city: str = "SINT-MARTENS-LATEM") -> dict:
        feat = [
            "CD_YEAR",
            "CD_TYPE_NL",
            "CD_REFNIS_NL",
            "MS_P_25",
            "MS_P_50_median",
            "MS_P_75",
            "CD_PERIOD",
            "CD_niveau_refnis",
        ]

        df_result = self.df_house[self.df_house["CD_REFNIS_NL"] == city]

        if df_result.empty:
            return None

        df_result = df_result[
            df_result.CD_YEAR
            == df_result.sort_values(["CD_YEAR"], ascending=False)
            .iloc[0]
            .to_dict()["CD_YEAR"]
            - 1
        ]
        # Previous year, since that would make the data more consitent and there should not be that big of a difference...

        # df_unique_type = df_house['CD_TYPE_NL'].unique() --> 4 unique types

        df_result = df_result[feat]

        out_dict = {
            "cd_year": df_result.CD_YEAR.tolist()[0],
            "cd_refnis": df_result.CD_REFNIS_NL.tolist()[0],
        }
        for (
            cd_year,
            cd_type,
            cd_refnis,
            msp25,
            msp50,
            msp75,
            cd_period,
            cd_niveau,
        ) in df_result.itertuples(index=False, name=None):
            if cd_type == "Appartementen":
                prefix = "AP"
            elif cd_type == "Huizen met 2 of 3 gevels (gesloten + halfopen bebouwing)":
                prefix = "HH"
            elif cd_type == "Huizen met 4 of meer gevels (open bebouwing)":
                prefix = "OH"
            elif (
                cd_type
                == "Alle huizen met 2, 3, 4 of meer gevels (excl. appartementen)"
            ):
                prefix = "AH"
            else:
                raise BrokenPipeError("It should not reach in here...")
            prefix = f"{cd_period}_{prefix}"

            out_dict[f"{prefix}_msp25"] = msp25
            out_dict[f"{prefix}_msp50"] = msp50
            out_dict[f"{prefix}_msp75"] = msp75
            out_dict[f"{prefix}_niveau"] = cd_niveau

        return out_dict

    # TODO no longer works
    # new api: https://www.vlaanderen.be/digitaal-vlaanderen/onze-diensten-en-platformen/geografische-webdiensten/ons-api-aanbod/capakey-rest-service
    def _get_perceel_insight(self, in_dict):
        def add_surface(input):
            input["surface"] = shape(
                json.loads(input["geometry"]["shape"].split(',"crs')[0] + "}")
            ).area
            return input

        def get_perceel(x, y):
            response = requests.get(
                f"https://geoservices.informatievlaanderen.be/capakey/api/v2/parcel?x={x}&y={y}&geometry=full&srs=31370&data=cadgis&status=fiscal"
            ).json()
            return {} if "Message" in response.keys() else add_surface(response)

        perceel_data = get_perceel(
            in_dict["Location"]["X_Lambert72"], in_dict["Location"]["Y_Lambert72"]
        )

        return {**in_dict, **perceel_data}

    # TODO usefullness and possibility without the original api (no consistent Municipality provided by Nominatim)?
    # municipality could be taken from sector information
    def _get_company_info(self, in_dict):
        def get_company(
            straat: str,
            busnummer: str,
            gemeente: str,
            zipcode: Optional = None,
            box: Optional = None,
        ) -> dict:
            df_result = self.df_addr[self.df_addr.MunicipalityNL == gemeente]
            df_result = df_result[df_result.StreetNL == straat]
            df_result = df_result[df_result.HouseNumber == busnummer]
            df_result = df_result[df_result.Zipcode == zipcode]
            if box:
                df_result = df_result[df_result.Box == box]

            if df_result.empty:
                return {}

            output = []
            for (
                e_number,
                type_addr,
                _,
                _,
                _,
                _,
                _,
                _,
                _,
                _,
                _,
                _,
                _,
            ) in df_result.itertuples(index=False, name=None):
                output.append({"Entiteit": e_number, "type": type_addr})

            return {"entiteiten": output}

        def get_entity_info(in_dict: dict) -> dict:
            enterprise_number = in_dict["Entiteit"]
            # Appending enterprise data
            df_enterprise = self.df_enterprise[
                self.df_enterprise.EnterpriseNumber == enterprise_number
            ].copy()
            df_enterprise.drop("EnterpriseNumber", axis=1, inplace=True)
            if not df_enterprise.empty:
                enterprise_info = df_enterprise.iloc[0].to_list()
                in_dict[f"{enterprise_number}_Status"] = enterprise_info[0]
                in_dict[f"{enterprise_number}_JuridicalSituation"] = enterprise_info[1]
                in_dict[f"{enterprise_number}_TypeOfEnterprise"] = enterprise_info[2]
                in_dict[f"{enterprise_number}_JuridicalForm"] = enterprise_info[3]
                in_dict[f"{enterprise_number}_StartDate"] = enterprise_info[4]
                # in_dict[f"{enterprise_number}_type"] = in_dict["type"]
            # df_ branch skipped, only startdate? --> already got that out of enterprise table
            in_dict.pop("type", None)
            in_dict.pop("Entiteit", None)
            return in_dict

        company = get_company(
            in_dict["Thoroughfarename"],  # road
            in_dict["Housenumber"],  # house_number
            in_dict["Municipality"],  # tx_munty_descr_nl
            in_dict["Zipcode"],  # postcode
        )

        if "entiteiten" not in company.keys():
            return {**in_dict, **{"entiteit_count": 0}}
        for entiteit in company["entiteiten"]:
            company = {**company, **get_entity_info(entiteit)}
        company["entiteit_count"] = len(company["entiteiten"])
        company.pop("entiteiten", None)
        return {
            **in_dict,
            **company,
        }

    # TODO only usefull if perceel_insight() and _get_company_info() work
    def _get_entity_density(self, finished_dict):
        if finished_dict["surface"] and finished_dict["entiteit_count"]:
            finished_dict["entiteit_per_m2"] = float(finished_dict["surface"]) / float(
                finished_dict["entiteit_count"]
            )
        else:
            finished_dict["entiteit_per_m2"] = 1
        return finished_dict
