from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    executor_model: str = "gpt-4.1"
    openai_embed_model: str = "text-embedding-3-small"

    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "meta/llama-3.1-8b-instruct"

    elevenlabs_api_key: str = ""
    elevenlabs_stt_model: str = "scribe_v1"
    elevenlabs_tts_model: str = "eleven_flash_v2_5"
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"

    stt_provider: str = "elevenlabs"
    tts_provider: str = "elevenlabs"

    route_threshold: float = 0.75  # ≥ → запуск сценария
    clarify_threshold: float = 0.45  # ниже → неуверенность; два раза подряд → оператор
    fast_confidence_threshold: float = 0.85  # ниже → эскалация с быстрой модели на сильную
    use_fast_path: bool = True
    speculative_executor: bool = True  # исполнитель параллельно с роутером на репликах-продолжениях
    top_k_candidates: int = 0  # 0 = весь каталог в промпте; >0 = сужение эмбеддингами
    history_turns: int = 6

    data_dir: Path = ROOT / "data"
    cache_dir: Path = ROOT / ".cache"
    db_path: Path = ROOT / "traces.db"


settings = Settings()
