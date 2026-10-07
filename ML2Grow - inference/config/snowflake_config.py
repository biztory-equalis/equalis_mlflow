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

    Tries auth methods in this order:
      1. OAuth, using the session token Snowpark Container Services injects
         into every running container at `/snowflake/session/token`. No user
         or private key is needed — identity comes from the token. This is
         how `inference.py` authenticates when deployed as an SPCS job.
      2. Key-pair auth (`SF_PRIVATE_KEY_PATH`, optionally
         `SF_PRIVATE_KEY_PASSPHRASE`) — the local-development path, since
         Snowflake has been deprecating single-factor password auth.
      3. Password auth (`SF_PASSWORD`) — legacy fallback.

    Env vars use this project's `SF_*` convention (from `.env` locally), but
    also fall back to the `SNOWFLAKE_*` names SPCS auto-injects (account,
    host) so the same config works unmodified in both places.
    """

    user: str | None = None
    password: str | None = None
    account: str | None = None
    database: str | None = None
    schema: str | None = None
    warehouse: str | None = None
    role: str | None = None
    host: str | None = None
    private_key_path: str | None = None
    private_key_passphrase: str | None = None
    token_path: str = "/snowflake/session/token"

    def __post_init__(self):
        """Populate fields from environment variables if not provided."""
        load_dotenv()

        self.user = self.user or os.getenv("SF_USER") or os.getenv("SNOWFLAKE_USER")
        self.password = self.password or os.getenv("SF_PASSWORD")
        self.account = self.account or os.getenv("SF_ACCOUNT") or os.getenv("SNOWFLAKE_ACCOUNT")
        self.database = self.database or os.getenv("SF_DATABASE") or os.getenv("SNOWFLAKE_DATABASE")
        self.schema = self.schema or os.getenv("SF_SCHEMA") or os.getenv("SNOWFLAKE_SCHEMA")
        self.warehouse = self.warehouse or os.getenv("SF_WAREHOUSE") or os.getenv("SNOWFLAKE_WAREHOUSE")
        self.role = self.role or os.getenv("SF_ROLE") or os.getenv("SNOWFLAKE_ROLE")
        # Only needed for OAuth: SPCS-internal connectivity requires the
        # injected host, not the account-locator host SQLAlchemy derives.
        self.host = self.host or os.getenv("SF_HOST") or os.getenv("SNOWFLAKE_HOST")
        self.private_key_path = self.private_key_path or os.getenv("SF_PRIVATE_KEY_PATH")
        self.private_key_passphrase = self.private_key_passphrase or os.getenv(
            "SF_PRIVATE_KEY_PASSPHRASE"
        )
        self.token_path = os.getenv("SF_TOKEN_PATH", self.token_path)

    @property
    def use_oauth_auth(self) -> bool:
        """True when an SPCS session token is present — takes priority over
        any other auth method configured, since it means we're running as a
        container service rather than locally."""
        return os.path.exists(self.token_path)

    @property
    def use_key_pair_auth(self) -> bool:
        return not self.use_oauth_auth and bool(self.private_key_path)

    def _read_oauth_token(self) -> str:
        with open(self.token_path, "r") as f:
            return f.read()

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
        These are merged on top of (and override) whatever
        `connection_string()`'s URL resolves to, which is how the OAuth token
        and the key-pair private key get to the connector — neither can be
        encoded into the connection URL itself."""
        if self.use_oauth_auth:
            args: Dict[str, Any] = {
                "authenticator": "oauth",
                "token": self._read_oauth_token(),
            }
            # Overrides the `{account}.snowflakecomputing.com` host the
            # dialect derives from the URL — SPCS needs the injected host for
            # internal connectivity.
            if self.host:
                args["host"] = self.host
            return args
        if self.use_key_pair_auth:
            return {"private_key": self._load_private_key_der()}
        return {}

    def connection_string(self) -> URL:
        """
        Constructs the SQLAlchemy connection URL using the URL object.
        This handles URL encoding and query parameter construction robustly.
        """
        if not self.use_oauth_auth and not self.use_key_pair_auth and not self.password:
            raise ValueError(
                "Snowflake configuration is incomplete: running outside SPCS "
                f"(no token found at {self.token_path}) requires either "
                "SF_PASSWORD or SF_PRIVATE_KEY_PATH."
            )

        # OAuth (SPCS) doesn't need a user — identity comes from the token.
        required = [self.account, self.database, self.schema, self.warehouse]
        if not self.use_oauth_auth:
            required.append(self.user)
        if not all(required):
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
            username=None if self.use_oauth_auth else self.user,
            # OAuth and key-pair auth supply credentials via connect_args,
            # not the URL — a password here would make the connector try
            # multiple auth methods at once.
            password=None if (self.use_oauth_auth or self.use_key_pair_auth) else self.password,
            host=self.account,
            database=full_database_path,  # The account part acts as the host
            query=query_params,
        )

        # The resulting string will be in the correct format:
        # snowflake://{user}:{password}@{account}/{database}/{schema}?warehouse={warehouse}&role={role}
        return url
