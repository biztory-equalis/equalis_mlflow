from concurrent.futures import ThreadPoolExecutor

import pandas as pd
from tqdm.auto import tqdm

from config.collector_config import CollectorConfig
from config.dataset_config import DatasetConfig
from config.reader_config import ReaderConfig
from config.snowflake_config import SnowflakeConfig
from core.enriching import DataCollecter
from core.query_executor import QueryExecutor
from core.snapshot_manager import SnapshotManager
from core.snowflake_client import SnowflakeClient
from extractor.dossier_reader import DossierReader
from extractor.TCBB_reader import TCBBReader
from extractor.verweerders_reader import VerweerderReader

tqdm.pandas()

# TODO logger instead of prints
# TODO pydantic config loading from json
# TODO add query arguments to config
# TODO add filter columns to config?


class DataConstructor:
    """
    Orchestrates the data pipeline by assembling dependencies
    (Client, Executor, Manager) and instantiating Readers.
    """

    def __init__(self, TCBB_enable: bool = False, address_enabled: bool = False):
        self.TCBB_enable = TCBB_enable
        self.address_enabled = address_enabled
        # Assuming environment variables are set for a full connection
        snowflake_config = SnowflakeConfig()

        # Instantiate a global DatasetConfig to track versions
        self.global_dataset_config = DatasetConfig(
            dataset_versions={
                "dossiers": "6ebfa4dbf81f4856",
                "verweerders": "3e03637b6c5d2aae",
                "TCBB": "ffa34de4b0a8c4c1",
            }
        )

        # Reader configs specifying sql queries
        self.dossier_reader_config = ReaderConfig(
            main_query_file="sql/dossiers_query.sql",
            dataset_key="dossiers",
            subquery_files={
                "hoofddossier_ids_filter_query": "sql/partials/hoofddossier_filter.sql"
            },
        )

        self.verweerder_reader_config = ReaderConfig(
            main_query_file="sql/verweerders_query.sql",
            dataset_key="verweerders",
            subquery_files={
                "verweerder_id_filter": "sql/partials/verweerder_id_filter.sql"
            },
        )

        self.TCBB_reader_config = ReaderConfig(
            main_query_file="sql/TCBB_query.sql",
            dataset_key="TCBB",
            # subquery_files={
            #     "hoofddossier_ids_filter_query": "sql/partials/hoofddossier_filter.sql"
            #     "verweerder_id_filter": "sql/partials/verweerder_id_filter.sql"
            # },
        )

        self.collector_config = CollectorConfig(
            path_geojson="jsons/sh_statbel_statistical_sectors_31370_20250101.geojson",
            path_tax_sector="jsons/TF_PSNL_INC_TAX_SECTOR.txt",
            path_vastgoed="jsons/vastgoed_2010_9999.txt",
            path_adress="jsons/KboOpenData_0092_2021_10_Full/address.csv",
            path_enterprice="jsons/KboOpenData_0092_2021_10_Full/enterprise.csv",
        )

        # Client creates the SQLAlchemy Engine
        self.client = SnowflakeClient(
            snowflake_config.connection_string(), snowflake_config.connect_args()
        )

        # Executor uses the Engine
        self.executor = QueryExecutor(self.client.engine)

        # Snapshot Manager handles disk I/O
        self.snapshot_manager = SnapshotManager()

        print("finised initialisation")

    def create_feature_set(self, filter: list[str] | None = None) -> pd.DataFrame:
        dossier_reader = DossierReader(
            reader_config=self.dossier_reader_config,
            executor=self.executor,
            snapshot_manager=self.snapshot_manager,
            dataset_config=self.global_dataset_config,
        )

        print("created DossierReader")

        verweerder_reader = VerweerderReader(
            reader_config=self.verweerder_reader_config,
            executor=self.executor,
            snapshot_manager=self.snapshot_manager,
            dataset_config=self.global_dataset_config,
        )

        print("created VerweerderReader")

        TCBB_reader = TCBBReader(
            reader_config=self.TCBB_reader_config,
            executor=self.executor,
            snapshot_manager=self.snapshot_manager,
            dataset_config=self.global_dataset_config,
        )

        print("created TCBBReader")

        self.datacollector = DataCollecter(config=self.collector_config)

        print("created Datacollector")

        dossier_features = dossier_reader.get_features()

        print(
            "unique hoofddossier_ids: ",
            len(dossier_features["hoofddossier_id"].unique()),
        )

        print("get_features DossierReader DONE")

        # join dataframes
        verweerder_features = verweerder_reader.get_features()

        print(
            "unique verweerder_ids: ",
            len(verweerder_features["verweerder_id"].unique()),
        )

        verweerder_features["hoofddossier_id"] = verweerder_features[
            "hoofddossier_id"
        ].astype(str)

        # print(verweerder_features.isna().sum())

        # TODO prevents ading mostly duplicate rows upon merge, should keep a good address
        # verweerder_features.drop_duplicates(subset=["hoofddossier_id", "verweerder_id"])

        # only keep good address?
        # why extract features for every adress?
        if self.address_enabled:
            # reduce addresses to enrich
            verweerder_features = verweerder_features[
                verweerder_features["verweerder_adres"].isin(
                    verweerder_reader.good_addresses
                )
            ]
            # NOTE: uses geodecoder to go from address to coordinate -> takes WAY too long
            # feature_df = self._enrich_using_addresses(
            #     verweerder_features=verweerder_features
            # )

            # approximation using postcode -> pdf file (can omly take into account BE addresses)
            # verweerder_features.dropna(subset=["latitude", "longitude"])
            # feature_df = verweerder_features.progress_apply(
            #     lambda row: self.datacollector.enrich_data_point(
            #         row["longitude"], row["latitude"]
            #     ),
            #     axis=1,
            #     result_type="expand",
            # )

            feature_df = self.datacollector.enrich_data_point_v2(verweerder_features)

            feature_df = dossier_features.merge(
                verweerder_features, on=["hoofddossier_id"], how="left"
            )

            print("merge address features into verweerder features DONE")

        else:
            feature_df = dossier_features.merge(
                verweerder_features, on=["hoofddossier_id"], how="left"
            )

            # NOTE don't know the datetime of address changes so can't filter those
            # TODO should be done before merge with dossiers but causes a bunch of nans i don't want to deal with rn
            feature_df = feature_df[
                feature_df["verweerder_adres"].isin(verweerder_reader.good_addresses)
            ]

        print("merge features verweerders DONE")

        if self.TCBB_enable:
            """
            # features using information from multiple tables
            TCBB_features = feature_df.progress_apply(
                lambda row: TCBB_reader.get_features_from_subset(
                    row["verweerder_id"],
                    row["hoofddossier_id"],
                    None,
                    row["datumboeking"],
                ),
                axis=1,
                result_type="expand",
            )

            feature_df = feature_df.merge(
                TCBB_features,
                left_on=["hoofddossier_id", "datumboeking"],
                right_on=["tdos_id", "stop_timestamp"],
                how="left",
            )

            """
            # 1. Prepare the subset of feature_df needed by the reader
            # This keeps the main feature_df intact
            main_df_subset = feature_df[
                ["verweerder_id", "hoofddossier_id", "datumboeking"]
            ].copy()

            # 2. Call the vectorized method
            # It passes the keys and receives all calculated features
            TCBB_features = TCBB_reader.get_vectorized_features(main_df_subset)

            # 3. Merge the result back into feature_df
            feature_df = feature_df.merge(
                TCBB_features,
                on=["hoofddossier_id", "datumboeking"],
                how="left",
            )

            print("merge features TCBB DONE")

        # filter
        # feature_df.filter(items=filter)

        # drop duplicates that snuck in because of filling nans
        feature_df = feature_df.drop_duplicates()

        return feature_df

    def _enrich_using_addresses(
        self, verweerder_features: pd.DataFrame
    ) -> pd.DataFrame:
        print("creating address features")
        # TODO first merge adres information into verweerder_df
        # NOTE: address cleaning could be used to create features for more records
        keys = verweerder_features.dropna(subset=["gevangenis_key"])[
            "gevangenis_key"
        ].unique()

        print(f"amount of address that require enriching: {len(keys)}")

        def enrich(key):
            return key, self.datacollector.enrich_data_address(key)

        enriched = {}
        with ThreadPoolExecutor(max_workers=10) as executor:
            for key, result in tqdm(executor.map(enrich, keys), total=len(keys)):
                enriched[key] = result

        address_features = pd.json_normalize(enriched).T
        address_features.index.name = "gevangenis_key"
        address_features.reset_index(inplace=True)

        print("merging address features")

        feature_df = verweerder_features.merge(
            address_features, on=["gevangenis_key"], how="inner"
        )

        return feature_df
