import json

import pandas as pd

from config.dataset_config import DatasetConfig
from config.reader_config import ReaderConfig
from core.base_reader import BaseReader
from core.query_executor import QueryExecutor
from core.snapshot_manager import SnapshotManager
from utils import get_geboortedatum, get_leeftijd


# TODO no time tensitive
# TODO check fillna
# TODO verweerder adress change count global
class VerweerderReader(BaseReader):
    def __init__(
        self,
        reader_config: ReaderConfig,
        executor: QueryExecutor,
        snapshot_manager: SnapshotManager,
        dataset_config: DatasetConfig,
        postcode_json_path: str = "jsons/postcode_coordinates.json",
    ):
        super().__init__(reader_config, executor, snapshot_manager, dataset_config)

        self.postcode_json_path = postcode_json_path
        self.good_addresses = [
            "Domicilie",
            "Maatsch. Zetel",
            "Vestigingsadres",
            "Exploitatie zetel",
            "Verblijfplaats",
        ]

        self.address_dict = None
        self.agg = None

        self.add_transform(self.add_address_change_features)
        # not accurate, requires seperate query to take into account all verweerders
        self.add_transform(self.add_people_at_address_feature)

        # not usefull
        # # self.add_transform(self.add_geboortedatum_feature)
        self.add_transform(self.add_leeftijd_feature)
        self.add_transform(self.add_categorical_features)
        self.add_transform(self.add_clean_adress)

        # better to take the value from the geocode api that gets extracted based on the address
        self.add_transform(self.add_latitude_longitude)

    def apply_initial_filter(self, verweerders: pd.DataFrame) -> pd.DataFrame:
        verweerders["hoofddossier_id"] = verweerders["hoofddossier_id"].astype(str)
        return verweerders[verweerders["verweerder_id"] != 0].copy()

    # NOTE doesn't work with the filter because not all verweerders from the dataset will be present in de df
    def _make_address_dict(
        self, verweerders: pd.DataFrame, good_addresses: list[str]
    ) -> dict[str, int]:
        # Filter to only "good" address types
        verweerders_good_address = verweerders[
            verweerders["verweerder_adres"].isin(good_addresses)
        ].copy()

        if verweerders_good_address.empty:
            return {}

        # Deduplicate by verweerder_id - only keep one address per person (if they have multiple, decide which one to take — e.g. the first)
        verweerders_unique = (
            verweerders_good_address.sort_values("gevangenis_key")
            .groupby("verweerder_id", as_index=False)
            .first()  # TODO takes the first row per verweerder_id, might want to take certain address types over others
        )

        # Now group by address (gevangenis_key) to see how many distinct people live there
        # NOTE Based on gevangenis_key which may have small difference that would still be the same address
        address_counts = (
            verweerders_unique.groupby("gevangenis_key")["verweerder_id"]
            .nunique()  # distinct verweerder_ids per address
            .reset_index(name="n_people")
        )

        address_dict = dict(
            zip(address_counts["gevangenis_key"], address_counts["n_people"])
        )

        return address_dict

    def add_people_at_address_feature(self, verweerders: pd.DataFrame) -> pd.DataFrame:
        """Computes and adds the count of unique people at the same address."""
        verweerders = verweerders.copy()

        # Compute the address lookup dictionary from the full data
        address_dict = self._make_address_dict(verweerders, self.good_addresses)

        # Define helper for mapping (to handle the default logic)
        def map_people_at(gevangenis_key: str) -> int:
            # Logic from original get_people_at: default to 1 if no information or not found
            if gevangenis_key == "---":
                return 1

            # Either return its value if in dict, or default to 1 if this verweerder had no address falling in a categorie belonging to good_addresses
            return int(address_dict.get(gevangenis_key, 1))

        # Apply the logic row-wise (using .apply() is simpler for this logic)
        verweerders["n_people_at_address"] = (
            verweerders["gevangenis_key"].apply(map_people_at).astype(int)
        )

        return verweerders

    def add_address_change_features(self, verweerders: pd.DataFrame) -> pd.DataFrame:
        """Computes and adds the number of address changes per hoofddossier_id based on number of unique verweerder_straat_clean values in the groupby"""
        verweerders = verweerders.copy()

        def _make_address_changes_agg(verweerders: pd.DataFrame) -> pd.DataFrame:
            agg = (
                verweerders[verweerders["gevangenis_key"] != "---"]
                .groupby("hoofddossier_id")
                .agg(
                    verweerder_id_nunique=("verweerder_id", "nunique"),
                    verweerder_id_max=("verweerder_id", "max"),
                    verweerder_postcode_nunique=("verweerder_postcode", "nunique"),
                    gevangenis_key_nunique=("gevangenis_key", "nunique"),
                    verweerder_straat_clean_nunique=(
                        "verweerder_straat_clean",
                        "nunique",
                    ),
                )
            ).reset_index()

            # filter out verweerder_id == 0 and hoofdossier_id with multiple unique verweerder_ids
            agg = agg[
                (agg["verweerder_id_nunique"] == 1) & (agg["verweerder_id_max"] > 0)
            ]
            return agg

        # Compute the aggregation table from the full data
        agg_table = _make_address_changes_agg(verweerders)

        # Filter out non feature columns
        feature_cols = [
            "verweerder_straat_clean_nunique",
            "verweerder_postcode_nunique",
            "gevangenis_key_nunique",
        ]

        merge_cols = [
            "hoofddossier_id",
        ] + feature_cols

        # Merge the feature result back onto the row-level data
        verweerders = verweerders.merge(
            agg_table[merge_cols],
            on="hoofddossier_id",
            how="left",
        )

        # Fill NaNs (if hoofddossier was filtered out or has no changes) with 1
        verweerders[feature_cols] = verweerders[feature_cols].fillna(1).astype(int)

        return verweerders

    # NOTE ******* useless because api converts back to age number
    def add_geboortedatum_feature(self, verweerders: pd.DataFrame) -> pd.DataFrame:
        """Computes a birthdate estimate based on age/category and adds it."""
        verweerders = verweerders.copy()

        # Apply the logic row-wise
        verweerders["estimated_geboortedatum"] = verweerders.apply(
            lambda row: get_geboortedatum(
                get_leeftijd(
                    row["verweerder_leeftijd"], row["verweerder_leeftijdscategorie"]
                )
            ),
            axis=1,
        )

        return verweerders

    def add_leeftijd_feature(self, verweerders: pd.DataFrame) -> pd.DataFrame:
        """Computes a birthdate estimate based on age/category and adds it."""
        verweerders = verweerders.copy()

        # Apply the logic row-wise
        verweerders["estimated_leeftijd"] = verweerders.apply(
            lambda row: get_leeftijd(
                row["verweerder_leeftijd"], row["verweerder_leeftijdscategorie"]
            ),
            axis=1,
        )

        return verweerders

    def add_categorical_features(self, verweerders: pd.DataFrame) -> pd.DataFrame:
        # NOTE nans also put as False
        verweerders["business"] = verweerders["verweerder_b2b_b2c"] == "B2B"

        verweerders["verweerder_leeftijdscategorie"] = verweerders[
            "verweerder_leeftijdscategorie"
        ].astype("category")

        verweerders["verweerder_provincie"] = (
            verweerders["verweerder_provincie"].fillna("Onbekend").astype("category")
        )

        verweerders["verweerder_gewest"] = verweerders["verweerder_gewest"].astype(
            "category"
        )

        return verweerders

    # TODO use verweerder_straat_clean instead of verweerder_straat ???
    # TODO huisnr is brol
    # TODO alleen belgische adressen
    # records met Belgische brol adressen uitfilteren?
    def add_clean_adress(self, verweerders: pd.DataFrame) -> pd.DataFrame:
        # Remove very small amount of verweerder without valid address
        # verweerders = verweerders.query("verweerder_gewest != 'Adres onbekend'").copy()

        nr_clean = (
            verweerders["verweerder_nr"].fillna("0").astype(str).str.split("/").str[0]
        )

        postcode_clean = (
            verweerders["verweerder_postcode"].fillna(0).astype(int).astype(str)
        )

        verweerders["adres"] = (
            verweerders["verweerder_straat_clean"]
            .str.cat(nr_clean, sep=" ")
            .str.cat(postcode_clean, sep=" ")
            .str.cat(verweerders["verweerder_gemeente"], sep=" ")
        ).str.strip()

        nan_mask = verweerders["verweerder_gewest"] == "Adres onbekend"
        # nan_mask = (
        #     verweerders[
        #         [
        #             "verweerder_straat_clean",
        #             "verweerder_gemeente",
        #             "verweerder_postcode",
        #             "verweerder_nr",
        #         ]
        #     ]
        #     .isna()
        #     .any(axis=1)
        # )
        verweerders.loc[nan_mask, "adres"] = pd.NA

        # print(verweerders.isna().sum())

        return verweerders

    # TODO alleen belgische postcodes in de json?
    # wat doen met buitenlands adressen?
    # geocoding api paid
    def add_latitude_longitude(self, verweerders: pd.DataFrame) -> pd.DataFrame:
        with open(self.postcode_json_path) as json_file:
            postcodes: dict = json.load(json_file)

        # Helper function to add values form dict and 0 if missing
        def _get_coordinates(postcode):
            if postcode in postcodes.keys():
                return postcodes[postcode]
            else:
                return {"latitude": 0, "longitude": 0}
                # return {"latitude": pd.NA, "longitude": pd.NA}

        # verweerders zonder postcode een 0 geven
        verweerders["verweerder_postcode"] = (
            verweerders["verweerder_postcode"].fillna(0).astype(int).astype(str)
        )

        verweerders["latitude"] = verweerders["verweerder_postcode"].apply(
            lambda x: _get_coordinates(x)["latitude"]
        )
        verweerders["longitude"] = verweerders["verweerder_postcode"].apply(
            lambda x: _get_coordinates(x)["longitude"]
        )
        return verweerders
