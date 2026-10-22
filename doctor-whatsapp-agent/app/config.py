"""Runtime configuration. Everything comes from environment variables / .env."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- LLM ---
    anthropic_api_key: str = ""                   # read from .env; the SDK also accepts the env var or `ant auth login`
    anthropic_workspace_id: str = ""              # required (wrkspc_...) when the key is org-scoped rather than workspace-scoped
    agent_model: str = "claude-opus-5-5"          # drafts, intake, patient replies
    classifier_model: str = "claude-haiku-5-5"    # cheap per-message triage (optional second pass)
    agent_effort: str = "low"                     # low | medium | high
    enable_fallbacks: bool = False                # server-side refusal fallback (beta); see README
    dry_run: bool = True                          # True = never call WhatsApp; print outbound instead

    # --- WhatsApp Cloud API ---
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = "change-me"
    whatsapp_app_secret: str = ""                 # for X-Hub-Signature-256 verification (recommended)
    whatsapp_api_version: str = "v22.0"

    # --- Doctor / clinic identity (injected into the system prompt) ---
    doctor_control_number: str = ""               # E.164 digits, no '+'. Drafts & pages go here; commands come from here.
    doctor_name: str = "Mehta"
    doctor_qualifications: str = "MBBS, MD"
    speciality: str = "General Physician"
    nmc_reg_no: str = "MCI-000000"
    clinic_name: str = "Mehta Clinic"
    city: str = "Mumbai"
    clinic_phone: str = "+91 00000 00000"
    assistant_name: str = "Seva"
    regional_languages: str = "Marathi"
    consent_notice: str = (
        "Namaste! This number uses an AI assistant to help with appointments and messages when the doctor is busy. "
        "Your messages are stored securely and seen only by the clinic. Reply to continue, or type STOP to opt out."
    )

    # --- Behaviour ---
    default_mode: str = "auto"                    # auto | draft | off
    backoff_minutes: int = 10                     # stay silent this long after the doctor replies in a thread
    holding_eta_minutes: int = 60                 # fallback ETA quoted to patients when calendar has no info

    # --- Storage / data ---
    database_url: str = "sqlite:///./sevadesk.db"
    kb_path: str = "data/clinic_kb.json"
    calendar_path: str = "data/calendar.json"
    reports_path: str = "data/reports.json"

    # --- Optional speech-to-text for voice notes (Sarvam Saaras) ---
    sarvam_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
