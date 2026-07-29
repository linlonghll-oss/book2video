from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./book2video.db"
    # Used by Fernet to encrypt API keys at rest.
    # If empty, a key file (storage/.fernet_key) is auto-generated on first run.
    ENCRYPTION_KEY: str = ""

    # LLM (OpenAI-compatible, works with Ollama / DeepSeek / Qwen / GLM / SiliconFlow etc.)
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "http://localhost:11434/v1"
    LLM_MODEL: str = "qwen2.5:7b"

    # Image generation (SiliconFlow / Replicate / OpenAI-compatible)
    IMAGE_API_KEY: str = ""
    IMAGE_BASE_URL: str = "https://api.siliconflow.cn/v1"
    IMAGE_MODEL: str = "Qwen/Qwen-Image"

    # Free image generation models
    # Pollinations.ai — completely free, no API key needed for anonymous use
    # Register at enter.pollinations.ai for higher limits (optional)
    POLLINATIONS_API_KEY: str = ""
    # Google Gemini 2.5 Flash Image — 500 free images/day
    # Get API key at aistudio.google.com (no credit card required)
    GEMINI_API_KEY: str = ""

    # Video generation (SiliconFlow video API)
    VIDEO_API_KEY: str = ""
    VIDEO_BASE_URL: str = "https://api.siliconflow.cn/v1"
    VIDEO_MODEL: str = "Wan-AI/Wan2.2-T2V-A14B"

    # TTS (edge-tts is free, no key needed; volcengine as optional)
    TTS_ENGINE: str = "edge-tts"
    TTS_API_KEY: str = ""
    TTS_VOICE: str = "zh-CN-XiaoxiaoNeural"

    # Legacy keys (kept for backward compat, mapped to new fields)
    ANTHROPIC_API_KEY: str = ""
    REPLICATE_API_KEY: str = ""
    VOLCENGINE_API_KEY: str = ""

    # Replicate (free credits for new accounts)
    REPLICATE_API_TOKEN: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
