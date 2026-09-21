from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class DatasetConfig:
    """Holds the current version state of all cached datasets."""

    dataset_versions: Dict[str, Optional[str]] = field(default_factory=dict)
    # Example: {"dossiers": "20231125_103000", "verweerders": None}
