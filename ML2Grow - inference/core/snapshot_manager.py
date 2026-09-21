from pathlib import Path

import pandas as pd


class SnapshotManager:
    """Handles saving and loading of DataFrame snapshots (disk caching)."""

    def __init__(self, root_dir: str = "data"):
        self.root = Path(root_dir)
        # Ensure the cache directory exists
        self.root.mkdir(parents=True, exist_ok=True)

    def file(self, name: str, version: str) -> Path:
        """Constructs the full path for a versioned snapshot file."""
        return self.root / f"{name}_{version}.parquet"

    def load(self, name: str, version: str) -> pd.DataFrame:
        """Loads a specific versioned snapshot."""
        path = self.file(name, version)
        if not path.exists():
            raise FileNotFoundError(f"Snapshot not found: {path.resolve()}")
        # Use fast Parquet reading
        return pd.read_parquet(path)

    def metadata_file(self, name: str, version: str) -> Path:
        """Constructs the full path for a versioned metadata file (TXT)."""
        return self.root / f"{name}_{version}.metadata.txt"

    def save(
        self,
        name: str,
        version: str,
        df: pd.DataFrame,
        logic_content: str,
    ) -> None:
        """Saves the DataFrame and its logic metadata."""

        # Save the data (Parquet file)
        data_path = self.file(name, version)
        df.to_parquet(data_path, index=False)
        print(f"[{self.__class__.__name__}] Saved data to: {data_path}")

        # Save the metadata (TXT file)
        metadata_path = self.metadata_file(name, version)
        with open(metadata_path, "w") as f:
            f.write(logic_content)
        print(f"[{self.__class__.__name__}] Saved metadata to: {metadata_path}")
