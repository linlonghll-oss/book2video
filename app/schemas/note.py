from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Optional


class NoteCreate(BaseModel):
    title: str
    content: Optional[str] = None
    raw_text: Optional[str] = None
    folder_id: Optional[int] = None


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    raw_text: Optional[str] = None
    folder_id: Optional[int] = None
    status: Optional[str] = None
    refined_title: Optional[str] = None
    refined_body: Optional[str] = None
    styled_body: Optional[str] = None


class NoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: Optional[str] = None
    raw_text: Optional[str] = None
    refined_title: Optional[str] = None
    refined_body: Optional[str] = None
    styled_body: Optional[str] = None
    folder_id: Optional[int] = None
    status: str
    created_at: datetime
    updated_at: datetime


class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None


class FolderUpdate(BaseModel):
    name: str


class FolderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    parent_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    children: list["FolderResponse"] = []


class ScriptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    note_id: int
    version: int
    style: Optional[str] = None
    content: Optional[dict] = None
    raw_content: Optional[str] = None
    created_at: datetime


class MaterialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    note_id: int
    type: str
    url: Optional[str] = None
    local_path: Optional[str] = None
    prompt: Optional[str] = None
    meta_data: Optional[dict] = None
    duration: Optional[float] = None
    created_at: datetime


class VideoOutputResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    note_id: int
    url: Optional[str] = None
    local_path: Optional[str] = None
    duration: Optional[float] = None
    resolution: Optional[str] = None
    file_size: Optional[int] = None
    meta_data: Optional[dict] = None
    created_at: datetime


class RefineRequest(BaseModel):
    model_config_id: Optional[int] = None


class TtsRequest(BaseModel):
    voice: Optional[str] = None
    tts_style: Optional[str] = None


class OptimizeRequest(BaseModel):
    style: Optional[str] = None
    model_config_id: Optional[int] = None


class MaterialGenRequest(BaseModel):
    model_config_id: Optional[int] = None
    llm_config_id: Optional[int] = None
    image_style: Optional[str] = None


class ComposeRequest(BaseModel):
    resolution: Optional[str] = "1920x1080"
    model_config_id: Optional[int] = None


class SlideGenRequest(BaseModel):
    model_config_id: Optional[int] = None
    model_id: Optional[str] = None  # Direct model_id (for free models, bypasses DB config)
    llm_config_id: Optional[int] = None
    image_style: Optional[str] = None
    text_style: Optional[str] = None  # "default", "bold", "elegant", "playful", "tech", "magazine"
    output_format: Optional[str] = "pptx"  # "pptx" or "xiaohongshu"
    gemini_api_key: Optional[str] = None  # Gemini API key for free model (aistudio.google.com)


class XhsGenRequest(BaseModel):
    """Dedicated Xiaohongshu generation request — simplified, no DB config needed."""
    model_id: str = "pollinations-flux"  # Free model ID
    title: str  # Post title
    content: str  # Full post content (will be split into pages)
    image_style: Optional[str] = "realistic"  # Visual style
    gemini_api_key: Optional[str] = None  # Only needed for gemini-flash-image


class RegenerateRequest(BaseModel):
    model_config_id: Optional[int] = None


# ---------- ModelConfig ----------

class ModelConfigCreate(BaseModel):
    name: str
    provider: str
    model_id: str
    api_key: Optional[str] = None
    params: Optional[dict] = None
    is_default: Optional[bool] = False


class ModelConfigUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    model_id: Optional[str] = None
    api_key: Optional[str] = None
    params: Optional[dict] = None
    is_default: Optional[bool] = None


class ModelConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    provider: str
    model_id: str
    api_key_masked: str
    params: Optional[dict] = None
    is_default: bool
    created_at: datetime
    updated_at: datetime
