from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    session_secret: str = "dev-secret-change-me"
    data_dir: Path = Path("./data")

    swap_backend: str = "mock"  # "mock" or "runpod"
    runpod_api_key: str = ""
    runpod_endpoint_id: str = ""
    public_base_url: str = "http://localhost:8000"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def outputs_dir(self) -> Path:
        return self.data_dir / "outputs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"


settings = Settings()
settings.uploads_dir.mkdir(parents=True, exist_ok=True)
settings.outputs_dir.mkdir(parents=True, exist_ok=True)
