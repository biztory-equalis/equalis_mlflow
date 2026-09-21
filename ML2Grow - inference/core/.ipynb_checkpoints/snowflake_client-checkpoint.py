from typing import Union

from sqlalchemy import create_engine
from sqlalchemy.engine.url import URL


class SnowflakeClient:
    """
    Manages the SQLAlchemy engine connection for Snowflake.

    The constructor accepts either a standard connection string (str) or a
    pre-constructed SQLAlchemy URL object, promoting better type safety and
    object-oriented design.
    """

    def __init__(self, connection_url: Union[str, URL]):
        self.engine = create_engine(connection_url)
