from typing import Any, Dict, Optional

import pandas as pd
from sqlalchemy.engine import Engine


class QueryExecutor:
    """
    Manages execution of SQL queries against the database engine.
    """

    def __init__(self, engine: Engine):
        self.engine = engine

    def execute(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
        **read_sql_kwargs: Any,
    ) -> pd.DataFrame:
        """
        Executes a query and returns a DataFrame.

        :param query: The final, resolved SQL query string.
        :param params: Dictionary of parameters for SQL placeholders (e.g., %(date)s).
        :param read_sql_kwargs: Additional arguments for pd.read_sql (e.g., parse_dates).
        :return: DataFrame result.
        """

        # Execute query with all supported options
        df = pd.read_sql(
            sql=query,
            con=self.engine,
            params=params,
            **read_sql_kwargs,
        )

        return df
