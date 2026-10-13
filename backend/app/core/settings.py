from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env lives at the repo root. Real environment variables (e.g. in CI) take precedence.
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    database_url: str
    # Host names the API answers to. Anything else is refused, which stops DNS rebinding (a
    # website re-pointing its own name at this machine). Add the Tailscale name in M4.
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]


settings = Settings()
