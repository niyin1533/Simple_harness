"""@input Environment settings. @output Application and isolated publication Redis configuration. @position Infrastructure.
@doc-sync Update this header and folder INDEX.md when this file changes.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_prefix="AGENT_", extra="ignore"
    )
    database_url: str = "mysql+asyncmy://agent:agent-local-only@127.0.0.1:13310/agent_harness?charset=utf8mb4"
    data_dir: Path = ROOT / "data"
    origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    secure_cookie: bool = False
    upload_limit_mb: int = 2048
    workers: int = 4
    network_hosts: str = ""
    command_allowlist: str = "git,python,python3,node,npm,npx,java,mvn"
    app_origin: str = "http://127.0.0.1:8011"
    session_hours: int = 24
    redis_url: str = "redis://127.0.0.1:16379/0"


settings = Settings()
