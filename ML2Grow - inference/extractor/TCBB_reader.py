import re
from datetime import datetime
from typing import ClassVar, Dict, List

import numpy as np
import pandas as pd

from config.dataset_config import DatasetConfig
from config.reader_config import ReaderConfig
from core.base_reader import BaseReader
from core.query_executor import QueryExecutor
from core.snapshot_manager import SnapshotManager


class TCBBReader(BaseReader):
    """
    Reader for the DOSSIERS dataset.
    It combines the strict DI constructor (from BaseReader) with the specific
    SQL and transformation logic for calculating cumulative bedrag.
    """

    type_beslagen: ClassVar[Dict[str, List[str]]]  # Defined as ClassVar

    def __init__(
        self,
        reader_config: ReaderConfig,
        executor: QueryExecutor,
        snapshot_manager: SnapshotManager,
        dataset_config: DatasetConfig,
    ):
        super().__init__(reader_config, executor, snapshot_manager, dataset_config)
        self.set_read_options(
            parse_dates=["timestampneerlegging", "timestampwijziging"]
        )

        self.auto_merken = [
            "abarth",
            "alfa romeo",
            "alpine",
            "aston martin",
            "audi",
            "bentley",
            "bmw",
            "bugatti",
            "cadillac",
            "caterham",
            "chevrolet",
            "citroën",
            "citroen",
            "cupra",
            "dacia",
            "ferrari",
            "fiat",
            "ford",
            "honda",
            "hyundai",
            "jaguar",
            "jeep",
            "kia",
            "ktm",
            "lamborghini",
            "land rover",
            "lexus",
            "lotus",
            "maserati",
            "mazda",
            "mclaren",
            "mercedes",
            "mini",
            "mitsubishi",
            "morgan",
            "nissan",
            "opel",
            "peugeot",
            "polestar",
            "porsche",
            "renault",
            "rolls-royce",
            "seat",
            "skoda",
            "smart",
            "ssangyong",
            "subaru",
            "suzuki",
            "tesla",
            "toyota",
            "tvr",
            "volkswagen",
            "volvo",
        ]

        self.type_beslagen = {
            "sommen": ["sommen", "sommes"],
            "huisraad": ["huisraad", "meubilair"],
            "voertuig": ["voertuig", "wagen", "auto", "nummerplaat", "nrplaat"]
            + self.auto_merken,
            "loon": ["loon"],
            "uitkering": ["uitkering"],
            "flatscreen": ["flat"],
            "huis_eigendom": [" gelegen "],
        }

        # Use ClassVar definition
        TCBBReader.type_beslagen = {
            "sommen": ["sommen", "sommes"],
            "huisraad": ["huisraad", "meubilair"],
            "voertuig": ["voertuig", "wagen", "auto", "nummerplaat", "nrplaat"]
            + self.auto_merken,
            "loon": ["loon"],
            "uitkering": ["uitkering"],
            "flatscreen": ["flat"],
            "huis_eigendom": [" gelegen "],
        }

    def apply_initial_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """Applies initial filtering/cleaning, used as a transform."""

        # Filter records where "bedrag" is nan or <= 0
        df = df[(df["bedrag"].notna()) & (df["bedrag"] > 0) & (df["tdos_id"] > 0)]

        # some records are duplicated in the database, should only contain 1 of every cbb_id, tdos_id (hoofddossier_id), tcbb_id (verweerder_id) pair
        df = df.drop_duplicates(subset=["cbb_id", "tcbb_id", "tdos_id"], keep="first")
        return df

    def get_relevant_tcbb_info(self, verweerder_id: int) -> pd.DataFrame:
        df = self.get_data
        filtered = df[df["tcbb_id"] == verweerder_id]

        return filtered.drop_duplicates(subset="cbb_id", keep="first")

    @staticmethod
    def filter_on_time(
        df: pd.DataFrame,
        start_timestamp: datetime | None = None,
        stop_timestamp: datetime | None = None,
    ) -> pd.DataFrame:
        # Start with a mask of all True values
        mask = pd.Series(True, index=df.index)

        if start_timestamp is not None:
            mask &= df["timestampneerlegging"] >= start_timestamp

        if stop_timestamp is not None:
            mask &= df["timestampneerlegging"] < stop_timestamp

        return df.loc[mask]

    # NOTE assumes only 1 verweerder linked to every hoofdossier_id
    def get_features_from_subset(
        self,
        verweerder_id: int,
        hoofdossier_id: int,
        start_timestamp: datetime,
        stop_timestamp: datetime,
    ) -> dict[str, float]:
        feature_dict = {
            "start_timestamp": start_timestamp,
            "stop_timestamp": stop_timestamp,
            "tdos_id": hoofdossier_id,
        }

        # verweerder_id = tcbb_id
        # hoofddossier_id = tdos_id

        # NOTE er zijn meerdere tcbb_id gelinkt aan dezelfde tdos_id
        # mapping moet gebeuren met verweerder_id uit verweerder tabel

        filtered = self.get_relevant_tcbb_info(verweerder_id)
        filtered = self.filter_on_time(filtered, start_timestamp, stop_timestamp)

        if filtered["bedrag"].isna().sum() > 0:
            print(
                "WARNING there should be no nans in TCBB bedragen because of the query"
            )
            filtered["bedrag"].fillna(0)

        feature_dict["total_bedrag_in_beslag_genomen"] = sum(filtered["bedrag"])

        bedragen = filtered.loc[filtered["bedrag"] > 0, "bedrag"]
        if bedragen.empty:
            feature_dict["mean_bedrag_in_beslag_genomen"] = 0
            feature_dict["median_bedrag_in_beslag_genomen"] = 0
            feature_dict["min_bedrag_in_beslag_genomen"] = 0
            feature_dict["max_bedrag_in_beslag_genomen"] = 0
        else:
            feature_dict["mean_bedrag_in_beslag_genomen"] = bedragen.mean()
            feature_dict["median_bedrag_in_beslag_genomen"] = bedragen.median()
            feature_dict["min_bedrag_in_beslag_genomen"] = bedragen.min()
            feature_dict["max_bedrag_in_beslag_genomen"] = bedragen.max()

        feature_dict["aantal_beslag_berichten"] = len(filtered)

        text = filtered["beslagen_goederen"].fillna("").astype(str).str.lower()

        for beslag_type, keywords in self.type_beslagen.items():
            pattern = "|".join(map(re.escape, keywords))
            feature_dict[f"beslag_{beslag_type}_sum"] = (
                text.str.contains(pattern, regex=True, na=False).astype(int).sum()
            )

        return feature_dict

    # ----------------------

    # --- Assumptions for Refactoring ---
    # TCBB_reader.get_data is the DataFrame being filtered (The 'TCBB' dataset).
    # The column 'tcbb_id' in TCBB_reader.get_data corresponds to 'verweerder_id' in feature_df.
    # The column 'timestampneerlegging' in TCBB_reader.get_data is used for time filtering.
    # The column 'datumboeking' in feature_df is the 'stop_timestamp'.

    def get_vectorized_features(
        self,
        main_df_subset: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Calculates TCBB features for all rows in the input DataFrame using
        vectorized operations (merge and groupby).

        Args:
            main_df_subset: A DataFrame containing the linking columns
                            ('verweerder_id', 'hoofddossier_id', 'datumboeking').

        Returns:
            A DataFrame with calculated features linked by hoofddossier_id and datumboeking.
        """
        # 1. Prepare TCBB Data
        tcbb_data = self.get_data.copy()

        # Apply original filtering logic: drop duplicates and handle NaNs
        tcbb_data = tcbb_data.drop_duplicates(
            # depends on the groupby you want to do
            # subset=["tcbb_id", "cbb_id"],
            subset=["tdos_id", "tcbb_id", "cbb_id"],
            keep="first",
        )
        tcbb_data["bedrag"] = tcbb_data["bedrag"].fillna(0)

        # Pre-process text for keyword features once
        tcbb_data["beslagen_goederen_lower"] = (
            tcbb_data["beslagen_goederen"].fillna("").astype(str).str.lower()
        )

        # 2. Merge the two datasets
        merged_df = main_df_subset.merge(
            tcbb_data,
            left_on="verweerder_id",
            right_on="tcbb_id",
            how="inner",
        )

        # 3. Vectorized Time-Based Filtering
        # Keeps only TCBB records that occurred BEFORE the datumboeking (stop_timestamp)
        # time_mask = merged_df["timestampneerlegging"] < merged_df["datumboeking"]
        # filtered_merged_df = merged_df[time_mask].copy()
        filtered_merged_df = merged_df

        # Define grouping columns for the aggregation
        grouping_cols = ["hoofddossier_id", "datumboeking"]

        # Initialize a list to hold all feature calculation DataFrames
        feature_calculations = []

        # 4. Vectorized Feature Calculation (Aggregation)

        # --- A. Simple Aggregates ---
        simple_aggregates = (
            filtered_merged_df.groupby(grouping_cols)
            .agg(
                total_bedrag_in_beslag_genomen=("bedrag", "sum"),
                aantal_beslag_berichten=("tcbb_id", "count"),
            )
            .reset_index()
        )
        feature_calculations.append(simple_aggregates)

        # --- B. Conditional Aggregates (Bedragen > 0) ---
        positive_bedragen = filtered_merged_df[filtered_merged_df["bedrag"] > 0]

        conditional_aggregates = (
            positive_bedragen.groupby(grouping_cols)
            .agg(
                mean_bedrag_in_beslag_genomen=("bedrag", "mean"),
                median_bedrag_in_beslag_genomen=("bedrag", "median"),
                min_bedrag_in_beslag_genomen=("bedrag", "min"),
                max_bedrag_in_beslag_genomen=("bedrag", "max"),
            )
            .reset_index()
        )
        feature_calculations.append(conditional_aggregates)

        # --- C. Keyword/Text Features ---
        for beslag_type, keywords in self.type_beslagen.items():
            pattern = "|".join(map(re.escape, keywords))

            # Groupby and sum the boolean directly
            keyword_sum = (
                filtered_merged_df.assign(
                    match=filtered_merged_df["beslagen_goederen_lower"]
                    .str.contains(pattern, regex=True, na=False)
                    .astype(int)  # Convert boolean to 0/1 for sum
                )
                .groupby(grouping_cols)["match"]
                .sum()
                .reset_index()
            )

            keyword_sum.rename(
                columns={"match": f"beslag_{beslag_type}_sum"}, inplace=True
            )
            feature_calculations.append(keyword_sum)

        # 5. Consolidate Features
        # Start with unique keys from the input data to ensure all needed rows are present
        final_features = (
            main_df_subset[["hoofddossier_id", "datumboeking"]].drop_duplicates().copy()
        )

        for df in feature_calculations:
            # Merge all calculated aggregate DataFrames
            final_features = final_features.merge(
                df,
                on=["hoofddossier_id", "datumboeking"],
                how="left",
            )

        # Final cleanup: fill NaNs with 0 (as per original logic)
        numeric_cols = final_features.select_dtypes(include=np.number).columns
        final_features[numeric_cols] = final_features[numeric_cols].fillna(0)

        return final_features
