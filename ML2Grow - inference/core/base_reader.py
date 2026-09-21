from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from datetime import datetime
from functools import cached_property
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Self

import pandas as pd

from config.dataset_config import DatasetConfig
from config.reader_config import ReaderConfig
from core.query_executor import QueryExecutor
from core.snapshot_manager import SnapshotManager

# TODO move initial tranform(s) into a seperate list for data cleaning and then always add this list to the metadata


def load_sql_content(path: Path) -> str:
    """Loads a SQL query from a given file path."""
    try:
        with open(path, "r") as f:
            return f.read()
    except FileNotFoundError:
        # Resolve the path to show the full location for better debugging
        raise FileNotFoundError(
            f"SQL file not found at expected path: {Path(path).resolve()}"
        )


# Define the type for transformation functions (Data Prep)
TransformFn = Callable[[pd.DataFrame], pd.DataFrame]


class BaseReader(ABC):
    """
    Base class for reading and managing datasets, handling SQL assembly,
    caching (disk snapshots), and row-level data preparation (transforms).

    Subclasses must implement get_features() to perform the final aggregation.
    """

    # Pattern to find subquery placeholders like {self.some_name}
    _PLACEHOLDER_PATTERN = re.compile(r"\{([a-zA-Z0-9_]+)\}")

    def __init__(
        self,
        reader_config: ReaderConfig,  # Reader-specific configuration
        executor: QueryExecutor,  # Service for executing SQL
        snapshot_manager: SnapshotManager,  # Service for disk caching
        dataset_config: DatasetConfig,  # Global version tracking
    ):
        """Initializes the BaseReader with necessary services and configuration."""
        self.reader_config: ReaderConfig = reader_config
        self.executor: QueryExecutor = executor
        self.snapshot: SnapshotManager = snapshot_manager
        self.dataset_config: DatasetConfig = dataset_config

        # State for data transformations and query options (for pd.read_sql)
        self.transforms: List[TransformFn] = []
        self._query_options: Dict[str, Any] = {}

    @property
    def dataset_name(self) -> str:
        """Returns the unique key for this dataset."""
        return self.reader_config.dataset_key

    @property
    def current_version(self) -> Optional[str]:
        """Gets the configured snapshot version for this dataset."""
        return self.dataset_config.dataset_versions.get(self.dataset_name, None)

    def _resolve_subqueries(self, template: str) -> str:
        """Performs string substitution for all subqueries defined in ReaderConfig."""
        final_query: str = template

        for (
            placeholder_name,
            subquery_path_str,
        ) in self.reader_config.subquery_files.items():
            subquery_path = Path(subquery_path_str)
            subquery_content: str = load_sql_content(subquery_path)

            # The exact placeholder string to search for
            placeholder = f"{{{placeholder_name}}}"

            # Replace the placeholder with the subquery content
            final_query = final_query.replace(placeholder, subquery_content)

        # Ensure all expected placeholders were resolved
        unresolved = self._PLACEHOLDER_PATTERN.findall(final_query)
        if unresolved:
            raise ValueError(
                f"Unresolved subquery placeholders found: {unresolved}. "
                f"These must be defined in the ReaderConfig.subquery_files dictionary."
            )

        return final_query

    def get_sql(self) -> str:
        """Loads the main query and assembles the final, executable SQL string."""
        main_query_template: str = load_sql_content(
            Path(self.reader_config.main_query_file)
        )
        return self._resolve_subqueries(main_query_template)

    def add_transform(self, fn: TransformFn) -> Self:
        """Adds a transformation function (pd.DataFrame -> pd.DataFrame) for data preparation."""
        self.transforms.append(fn)
        return self

    def set_query_params(self, **params: Any) -> Self:
        """Sets parameters for the SQL query (e.g., for use with %(param_name)s placeholders)."""
        # Store parameters under the 'params' key for pandas.read_sql
        self._query_options["params"] = params
        return self

    def set_read_options(self, **options: Any) -> Self:
        """Sets additional options for pandas.read_sql (e.g., parse_dates, dtype)."""
        # We enforce that params are set via set_query_params
        if "params" in options:
            raise ValueError(
                "Use set_query_params() to set SQL parameters, not set_read_options()."
            )
        self._query_options.update(options)
        return self

    def _run_query_and_transform(self) -> pd.DataFrame:
        """Executes the final query and applies registered transformations."""
        query: str = self.get_sql()

        # Execute the query
        df = self.executor.execute(
            query=query,
            **self._query_options,
        )

        return df

    # TODO include apply_initial_filtering in transforms even if no other transforms are applied
    def get_logic_metadata(self, with_transforms: bool = False) -> tuple[str, str]:
        """
        Generates a deterministic ID and the corresponding logic content string.
        Returns: (logic_hash, content_string)
        """
        # Get the final, assembled SQL query
        query_content: str = self.get_sql()

        # Collect metadata about the transformations

        if with_transforms:
            # Using __qualname__ ensures we get a stable name for each function
            transform_names = [t.__qualname__ for t in self.transforms]
            hash_input = f"SQL:{query_content}\nTRANSFORMS:{';'.join(transform_names)}"
        else:
            transform_names = []

        hash_input = f"SQL:{query_content}"
        if transform_names:
            hash_input += "\nTRANSFORMS:" + ";".join(transform_names)

        # Generate the stable hash (SHA256, truncated)
        # NOTE: The hash MUST be generated only from the query and transform NAMES,
        # not the timestamp or full metadata, to remain deterministic.
        # NOTE: also hashes comments so query can be functionally the same but with a different hash

        hash_object = hashlib.sha256(hash_input.encode("utf-8"))
        logic_hash = hash_object.hexdigest()[:16]

        # Concatenate all relevant content (this is the metadata you want to save)

        content_to_save = (
            f"DATASET: {self.dataset_name}\n"
            f"GENERATED_AT: {datetime.now().date().isoformat()}\n"
            f"HASH_ID: {logic_hash}\n"
            f"----------------------------------------\n"
            f"SQL QUERY:\n{query_content}\n"
            f"----------------------------------------\n"
        )

        if with_transforms:
            content_to_save += f"TRANSFORMATIONS:\n- {'\n- '.join(transform_names)}\n"

        # Return both the hash (for versioning) and the content (for saving)
        return logic_hash, content_to_save

    @abstractmethod
    def apply_initial_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        pass

    @cached_property
    def get_data(self) -> pd.DataFrame:
        """
        Retrieves the prepared, row-level dataset, loading from snapshot if available,
        otherwise running the query, applying transforms, and saving a new snapshot.
        """
        name = self.dataset_name
        version = self.current_version
        logic_hash, logic_content = self.get_logic_metadata()

        if version is None:
            print(
                f"[{name}] version is None({version} -> {logic_hash}). Re-running and saving."
            )
        elif version == logic_hash:
            try:
                print(f"[{name}] Loading snapshot version: {version}")
                return self.snapshot.load(name, version)
            except FileNotFoundError:
                print(
                    f"[{name}] Configured snapshot '{version}' not found. Re-running query."
                )
        else:
            print(f"[{name}] Logic hash changed ({version} -> {logic_hash}).")
            print(f"Checking if new logic hash {logic_hash} already exists")
            try:
                df = self.snapshot.load(name, logic_hash)
                print(f"Loaded {logic_hash}")
                return df
            except Exception:
                print("Rerunning query and saving")

        df = self._run_query_and_transform()

        self.snapshot.save(
            name=name, version=logic_hash, df=df, logic_content=logic_content
        )

        # Update config in memory
        self.dataset_config.dataset_versions[name] = logic_hash
        print(f"[{name}] New snapshot saved with version: {logic_hash}")

        # initial filter gets applied before feature extraction but after saving query output
        print(f"[{name}] apply_initial_filter")
        df = self.apply_initial_filter(df)

        return df

    def get_data_columns(self) -> list[str]:
        return sorted(self.get_data.columns)

    def get_features(
        self, apply_transfroms: bool = True, filter: list[str] | None = None
    ) -> pd.DataFrame:
        df = self.get_data

        if apply_transfroms:
            # Apply transformations (data preparation) sequentially
            for t in self.transforms:
                print(f"Applying transfrom : {t.__name__}")
                df = t(df)

        if filter:
            return df.filter(items=filter)
        else:
            return df
