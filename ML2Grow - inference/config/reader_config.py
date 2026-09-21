from dataclasses import dataclass, field
from typing import Dict


@dataclass
class ReaderConfig:
    """
    Configuration for a specific data reader, defining its data sources
    and how to combine them.
    """

    main_query_file: str
    dataset_key: str  # Unique name for the dataset (e.g., 'dossiers')

    # Mapping of placeholder name in main_query to the path of the subquery file
    subquery_files: Dict[str, str] = field(default_factory=dict)
