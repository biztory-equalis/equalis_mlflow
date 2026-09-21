import os
from dataclasses import dataclass
from typing import Any, Dict

from dotenv import load_dotenv

# Import the URL class from SQLAlchemy
from sqlalchemy.engine.url import URL


@dataclass
class SnowflakeConfig:
    """
    Holds credentials and connection details for Snowflake.
    Uses SQLAlchemy's URL object for robust connection string construction.

    Supports either password auth (`SF_PASSWORD`) or key-pair auth
    (`SF_PRIVATE_KEY_PATH`, optionally `SF_PRIVATE_KEY_PASSPHRASE`) — Snowflake
    has been deprecating single-factor password auth, so key-pair is the
    preferred option going forward. If both are set, key-pair auth wins.
    """

    user: str | None = None
    password: str | None = None
    account: str | None = None
    database: str | None = None
    schema: str | None = None
    warehouse: str | None = None
    role: str | None = None
    private_key_path: str | None = None
    private_key_passphrase: str | None = None

    def __post_init__(self):
        """Populate fields from environment variables if not provided."""
        load_dotenv()

        self.user = self.user or os.getenv("SF_USER")
        self.password = self.password or os.getenv("SF_PASSWORD")
        self.account = self.account or os.getenv("SF_ACCOUNT")
        self.database = self.database or os.getenv("SF_DATABASE")
        self.schema = self.schema or os.getenv("SF_SCHEMA")
        self.warehouse = self.warehouse or os.getenv("SF_WAREHOUSE")
        self.role = self.role or os.getenv("SF_ROLE")
        self.private_key_path = self.private_key_path or os.getenv("SF_PRIVATE_KEY_PATH")
        self.private_key_passphrase = self.private_key_passphrase or os.getenv(
            "SF_PRIVATE_KEY_PASSPHRASE"
        )

    @property
    def use_key_pair_auth(self) -> bool:
        return bool(self.private_key_path)

    def _load_private_key_der(self) -> bytes:
        """Reads the PEM private key file and returns it DER-encoded, as the
        Snowflake connector's `private_key` connect arg expects."""
        from cryptography.hazmat.primitives import serialization

        passphrase = (
            self.private_key_passphrase.encode()
            if self.private_key_passphrase
            else None
        )

        with open(self.private_key_path, "rb") as key_file:
            p_key = serialization.load_pem_private_key(
                key_file.read(), password=passphrase
            )

        return p_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def connect_args(self) -> Dict[str, Any]:
        """Extra kwargs to pass to `create_engine(..., connect_args=...)`.
        Only key-pair auth needs this — the private key can't be encoded into
        the connection URL, unlike the password."""
        if self.use_key_pair_auth:
            return {"private_key": self._load_private_key_der()}
        return {}

    def connection_string(self) -> URL:
        """
        Constructs the SQLAlchemy connection URL using the URL object.
        This handles URL encoding and query parameter construction robustly.
        """
        if not self.use_key_pair_auth and not self.password:
            raise ValueError(
                "Snowflake configuration is incomplete: set either SF_PASSWORD "
                "or SF_PRIVATE_KEY_PATH."
            )

        if not all(
            [
                self.user,
                self.account,
                self.database,
                self.schema,
                self.warehouse,
            ]
        ):
            raise ValueError("Snowflake configuration is incomplete.")

        # Build the dictionary of query parameters for the URL
        query_params: Dict[str, Any] = {
            "warehouse": self.warehouse,
            "schema": self.schema,  # schema is often passed as a query param in newer drivers
        }

        if self.role:
            query_params["role"] = self.role

        # The database and schema paths are combined into the 'database' component
        # for many drivers, including Snowflake's SQLAlchemy connector.
        # We explicitly set the schema in query_params above for best practice.
        full_database_path = f"{self.database}"

        url = URL.create(
            drivername="snowflake",
            username=self.user,
            # Key-pair auth supplies the key via connect_args, not the URL —
            # a password here would make the connector try both at once.
            password=None if self.use_key_pair_auth else self.password,
            host=self.account,
            database=full_database_path,  # The account part acts as the host
            query=query_params,
        )

        # The resulting string will be in the correct format:
        # snowflake://{user}:{password}@{account}/{database}/{schema}?warehouse={warehouse}&role={role}
        return url
