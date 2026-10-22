"""Runtime configuration. Everything comes from environment variables / .env (never commit .env)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- LLM ---
    anthropic_api_key: str = ""
    anthropic_workspace_id: str = ""          # wrkspc_... when the key is org-scoped
    companion_model: str = "claude-sonnet-5-5"   # conversation
    classifier_model: str = "claude-haiku-5-5"   # pre-turn risk classifier
    guard_model: str = "claude-haiku-5-5"        # post-turn output guard
    effort: str = "low"
    use_llm_classifier: bool = True           # rules always run; the LLM can only raise the level
    use_llm_guard: bool = True                # regex hard checks always run; the LLM adds a second opinion
    llm_words_crisis: bool = True             # let the LLM reword scripted crisis text (structure fixed)

    # --- Product identity ---
    companion_name: str = "Saathi"
    default_language: str = "en"
    partner_counsellor_offer: str = "I can also connect you to a human counsellor from our team."
    handoff_instruction: str = "Type HUMAN at any time and a person from our team will be alerted."

    # --- Behaviour ---
    session_nudge_minutes: int = 60           # suggest a pause after this long in one session
    session_gap_minutes: int = 30             # silence longer than this starts a new session
    history_turns: int = 20                   # messages sent to the companion model
    reply_max_lines: int = 6

    # --- Storage ---
    database_url: str = "sqlite:///./saathi.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
