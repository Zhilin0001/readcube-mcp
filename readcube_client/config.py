import tomllib
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="READCUBE_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    session_file: Path = Path.home() / ".config/readcube-client/session.json"
    verification_file: Path = Path.home() / ".config/readcube-client/verified.json"
    state_dir: Path = Path.home() / ".local/state/readcube-client"
    email: str | None = None
    password: SecretStr | None = None
    client_version: str = "5.4.24"
    timeout: float = Field(default=30, gt=0, le=300)
    retries: int = Field(default=2, ge=0, le=5)
    min_interval: float = Field(default=0.25, ge=0)
    max_pages: int = Field(default=10000, ge=1)
    dry_run: bool = True
    write_collections: list[str] = Field(default_factory=list)
    upload_hosts: list[str] = Field(default_factory=lambda: ["sync.readcube.com"])
    upload_roots: list[Path] = Field(default_factory=list)
    upload_timeout: float = Field(default=120, gt=0, le=600)

    @field_validator("session_file", "verification_file", "state_dir", mode="after")
    @classmethod
    def expand_paths(cls, value: Path) -> Path:
        return value.expanduser()

    @field_validator("upload_roots", mode="after")
    @classmethod
    def expand_roots(cls, values: list[Path]) -> list[Path]:
        return [value.expanduser() for value in values]

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        return env_settings, dotenv_settings, init_settings, file_secret_settings

    @classmethod
    def from_toml(cls, path: str | Path | None = None):
        if path is None:
            return cls()
        with Path(path).open("rb") as file:
            return cls(**tomllib.load(file).get("readcube", {}))
