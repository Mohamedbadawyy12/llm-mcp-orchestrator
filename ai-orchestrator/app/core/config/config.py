# app/core/config.py

import yaml
from pathlib import Path
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Any, Dict

# Define the root directory of the project
BASE_DIR = Path(__file__).resolve().parent.parent.parent

def yaml_config_settings_source(settings: BaseSettings) -> Dict[str, Any]:
    """
    A settings source that loads variables from a YAML file.
    """
    config_file = BASE_DIR / "config" / "settings.yaml"
    if config_file.exists():
        with open(config_file, "r") as f:
            return yaml.safe_load(f)
    return {}

class Settings(BaseSettings):
    """
    Main application settings class.
    It inherits from pydantic_settings.BaseSettings, which allows it to automatically
    read settings from environment variables and other sources.
    """
    # --- General Settings ---
    project_name: str = "MCP AI Orchestrator"
    log_level: str = "INFO"
    debug: bool = False

    # --- API Keys ---
    # Pydantic will automatically try to find an environment variable
    # with this name (case-insensitive). e.g., GOOGLE_API_KEY
    google_api_key: str | None = None

    # --- Config Paths ---
    mcp_servers_config_path: str = "config/servers.json"
    agents_config_path: str = "config/agents.json"

    model_config = SettingsConfigDict(
        # Environment variables are case-insensitive
        case_sensitive=False,
        # Specify the file to read environment variables from (for local development)
        env_file=BASE_DIR / ".env",
        env_file_encoding='utf-8'
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """
        Define the priority of settings sources.
        1. init_settings (arguments passed to the constructor)
        2. env_settings (Environment variables)
        3. dotenv_settings (.env file)
        4. yaml_config_settings_source (our custom YAML file loader)
        5. file_secret_settings (Docker secrets)
        """
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            yaml_config_settings_source,
            file_secret_settings,
        )

# Create a single, reusable instance of the settings
settings = Settings()

# --- Example of how to use it ---
if __name__ == "__main__":
    print("--- Loaded Settings ---")
    print(f"Project Name: {settings.project_name}")
    print(f"Debug Mode: {settings.debug}")
    print(f"Google API Key: {'*' * 10 if settings.google_api_key else 'Not Set'}")
    print(f"Servers Config Path: {settings.mcp_servers_config_path}")
    print("-----------------------")
    # To test with an environment variable, run in your terminal:
    # export GOOGLE_API_KEY="my_real_api_key"
    # python app/core/config.py
