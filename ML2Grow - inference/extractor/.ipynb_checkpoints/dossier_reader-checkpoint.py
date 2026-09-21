import datetime

import pandas as pd

from config.dataset_config import DatasetConfig
from config.reader_config import ReaderConfig
from core.base_reader import BaseReader
from core.query_executor import QueryExecutor
from core.snapshot_manager import SnapshotManager

# TODO:
# y based on dassier_status ipv. solvabiliteit_dossier
# gerechterlijk minnelijk to bool


class DossierReader(BaseReader):
    """
    Reader for the DOSSIERS dataset.
    It combines the strict DI constructor (from BaseReader) with the specific
    SQL and transformation logic for calculating cumulative bedrag.
    """

    def __init__(
        self,
        reader_config: ReaderConfig,
        executor: QueryExecutor,
        snapshot_manager: SnapshotManager,
        dataset_config: DatasetConfig,
    ):
        super().__init__(reader_config, executor, snapshot_manager, dataset_config)

        self.cutoff_date = datetime.date(2015, 1, 1)

        # Mapping for weighted calculation
        self.action_map = {
            "AFVRW": -1,
            "AFVRWC": -1,
            "AFVRWD": -1,
            "BETAAN": 0,
            "BETBTK": 1,
            "BETKLA": 0,
            "CFRAFVRW": -1,
            "CFRDRSBES": -1,
            "CFRIRFIXED": 0,
            "CFRKSTFB": 0,
            "CFRREGDOS": 0,
            "DRSBES": 0,
            "DRSCFR": 0,
            "DRSREG": 0,
            "DRSRSZ": 0,
            "DRSVRW": 0,
            "HSMI": 1,
            "HSZI": 1,
            "INFOC": 0,
            "INT": 1,
            "INTDET": 0,
            "IR": 0,
            "IRFIXED": 0,
            "KSTFA": 1,
            "KSTFB": 1,
            "KSTFC": 1,
            "KSTFK": 0,
            "KSTREG": 1,
            "OH": 0,
            "PROAAN": 0,
            "PROKLA": 0,
            "PS": 0,
            "REGCFR": 0,
            "REGDOS": -1,
            "TOEKLT": 1,
            "VRWINT": 1,
            "None": 0,
        }

        self.dossier_status_code_map_reg = {
            "STPOPD": 0,
            "REGLE": 1,
            "TERU": -1,
            "GESM": 0,
            "STPZ": 0,
            "GZ": 0,
        }

        self.dossier_status_code_map_cat = {
            "STPOPD": 0,
            "REGLE": 1,
            "TERU": 0,
            "GESM": 0,
            "STPZ": 0,
            "GZ": 0,
        }

        # Set the query parameters for the SQL query (used by BaseReader's _run_query)
        # Assuming the SQL query uses %(date)s as a parameter placeholder
        self.set_query_params(date=self.cutoff_date)
        self.set_read_options(parse_dates=["datumboeking"])

        # Add features
        self.add_transform(self.get_cumulative_bedrag)
        self.add_transform(self.add_categorical_features)
        self.add_transform(self.add_label_features)

    # Filter records where "bedrag" is nan
    def apply_initial_filter(self, dossiers: pd.DataFrame) -> pd.DataFrame:
        """Applies initial filtering/cleaning, used as a transform."""
        return dossiers[dossiers["bedrag"].notna()]

    def get_cumulative_bedrag(self, dossiers: pd.DataFrame) -> pd.DataFrame:
        """
        Computes weighted cumulative bedrag for each hoofddossier_id.
        """

        # Compute weighted bedragen
        # Assuming 'booking_code' is present in the DataFrame fetched by the query
        dossiers["bedrag_weighted"] = (
            dossiers["bedrag"] * dossiers["booking_code"].map(self.action_map)
        ).fillna(0)

        # Sort by dossier and date
        dossiers = dossiers.sort_values(["hoofddossier_id", "datumboeking"])

        # Compute the cumulative sum (“sum up to this booking”)
        dossiers["bedrag_cumulatief"] = (
            dossiers.groupby("hoofddossier_id")["bedrag_weighted"].cumsum().round()
            # .astype(int)
        )

        return dossiers

    def add_categorical_features(self, dossiers: pd.DataFrame) -> pd.DataFrame:
        dossiers["gerechtelijk"] = dossiers["gerechterlijk_minnelijk"] == "Gerechtelijk"
        return dossiers

    def add_label_features(self, dossiers: pd.DataFrame) -> pd.DataFrame:
        # label for original classification model
        dossiers["y"] = dossiers["solvabiliteit_dossier"] == "Solvabel"

        # map dossier status_code to int as truth value for regressormodel
        # NOTE what with new types or running dossiers (should be filtered in query)?
        dossiers["dossier_status_label_reg"] = dossiers["dossier_status_code"].map(
            self.dossier_status_code_map_reg
        )

        dossiers["dossier_status_label_cat"] = dossiers["dossier_status_code"].map(
            self.dossier_status_code_map_cat
        )

        return dossiers
