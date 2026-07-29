import json
import logging
import os
import asyncio

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.db import get_db, async_session
from app.config import settings
from app.models.note import Note
from app.models.script import Script
from app.models.material import Material
from app.models.video_output import VideoOutput
from app.models.model_config import ModelConfig
from app.schemas.note import RefineRequest, OptimizeRequest, MaterialGenRequest, TtsRequest, ComposeRequest, SlideGenRequest, XhsGenRequest, RegenerateRequest, ScriptResponse, MaterialResponse, VideoOutputResponse
from app.services.parser import parse_markdown
from app.services.optimizer import optimize_script
from app.services.refiner import refine_text
from app.services.material_gen import generate_materials
from app.services.video_extract import save_upload_video, generate_materials_from_video
from app.services.video_gen import generate_segment_video
from app.services.composer import compose_video, generate_segment_clips, generate_subtitles
from app.services.slide_gen import generate_slides, generate_xhs_images, STYLE_METADATA, _is_free_model, FREE_IMAGE_MODELS, _build_xhs_prompts_from_template, _generate_xhs_bg_image, _render_xhs_cover, _render_xhs_content, _retry_image_generation, _generate_image_with_free_model, _infer_emotion_atmosphere, XHS_W, XHS_H, XHS_PALETTES
from app.routers.config import _decrypt_api_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["workflow"])

MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500MB
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm", ".mkv", ".flv"}

# Note-level locks to prevent concurrent workflow operations on the same note
_note_locks: dict[int, asyncio.Lock] = {}


def _get_note_lock(note_id: int) -> asyncio.Lock:
    """Return (or create) an asyncio.Lock for the given note_id."""
    if note_id not in _note_locks:
        _note_locks[note_id] = asyncio.Lock()
    return _note_locks[note_id]


@router.get("/notes/{note_id}/scripts/latest", response_model=ScriptResponse)
async def get_latest_script(note_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Script).where(Script.note_id == note_id).order_by(Script.version.desc()).limit(1)
    )
    script = result.scalar_one_or_none()
    if script is None:
        raise HTTPException(status_code=404, detail="No script found for this note")
    return ScriptResponse.model_validate(script)


@router.patch("/notes/{note_id}/scripts/{script_id}", response_model=ScriptResponse)
async def update_script(note_id: int, script_id: int, body: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Script).where(Script.id == script_id, Script.note_id == note_id)
    )
    script = result.scalar_one_or_none()
    if script is None:
        raise HTTPException(status_code=404, detail="Script not found")
    if "content" in body:
        if not isinstance(body["content"], (dict, list)):
            raise HTTPException(status_code=422, detail="content must be a JSON object or array")
        script.content = body["content"]
    if "raw_content" in body:
        if not isinstance(body["raw_content"], str):
            raise HTTPException(status_code=422, detail="raw_content must be a string")
        script.raw_content = body["raw_content"]
    if "style" in body:
        if not isinstance(body["style"], str):
            raise HTTPException(status_code=422, detail="style must be a string")
        script.style = body["style"]
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(script)
    return ScriptResponse.model_validate(script)


@router.get("/notes/{note_id}/materials", response_model=list[MaterialResponse])
async def list_note_materials(note_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Material).where(Material.note_id == note_id))
    return [MaterialResponse.model_validate(m) for m in result.scalars().all()]


@router.get("/notes/{note_id}/videos", response_model=list[VideoOutputResponse])
async def list_note_videos(note_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(VideoOutput).where(VideoOutput.note_id == note_id).order_by(VideoOutput.created_at.desc())
    )
    return [VideoOutputResponse.model_validate(v) for v in result.scalars().all()]


@router.post("/notes/{note_id}/input")
async def input_note(note_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    parsed = parse_markdown(note.raw_text or note.content or "")
    note.content = note.raw_text or note.content or ""
    note.status = "parsed"
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(note)
    return {"note_id": note.id, "status": note.status, "parsed": parsed}


@router.post("/notes/{note_id}/refine")
async def refine_note(note_id: int, body: RefineRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    model_config = None
    mc = None
    if body.model_config_id is not None:
        mc_result = await db.execute(select(ModelConfig).where(ModelConfig.id == body.model_config_id))
        mc = mc_result.scalar_one_or_none()
    if mc is None:
        # Fall back to default LLM config
        default_result = await db.execute(
            select(ModelConfig).where(ModelConfig.provider == "llm", ModelConfig.is_default == True)
        )
        mc = default_result.scalar_one_or_none()
    if mc:
        api_key = _decrypt_api_key(mc.api_key_encrypted) if mc.api_key_encrypted else None
        params = mc.params or {}
        model_config = {
            "provider": mc.provider,
            "model_id": mc.model_id,
            "api_key": api_key,
            "base_url": params.get("base_url"),
            "temperature": params.get("temperature"),
        }

    refined = await refine_text(
        title=note.title or "",
        body=note.raw_text or note.content or "",
        model_config=model_config,
    )

    if refined.get("status") == "error":
        raise HTTPException(status_code=500, detail=refined.get("message", "Refine failed"))

    if "title" not in refined or "body" not in refined:
        raise HTTPException(status_code=500, detail="Refine returned unexpected response")

    # Store refined text in separate columns, do NOT overwrite original
    note.refined_title = refined["title"]
    note.refined_body = refined["body"]
    note.status = "parsed"
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(note)
    return {"note_id": note.id, "status": note.status, "refined_title": note.refined_title, "refined_body": note.refined_body}


@router.post("/notes/{note_id}/optimize")
async def optimize_note(note_id: int, body: OptimizeRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    # Use refined text if available, otherwise fall back to original
    source_text = note.refined_body or note.raw_text or note.content or ""
    source_title = note.refined_title or note.title or ""
    parsed = parse_markdown(source_text)
    # Inject refined title if the parsed result doesn't have one
    if source_title and not parsed.get("title"):
        parsed["title"] = source_title

    model_config = None
    mc = None
    if body.model_config_id is not None:
        mc_result = await db.execute(select(ModelConfig).where(ModelConfig.id == body.model_config_id))
        mc = mc_result.scalar_one_or_none()
    if mc is None:
        default_result = await db.execute(
            select(ModelConfig).where(ModelConfig.provider == "llm", ModelConfig.is_default == True)
        )
        mc = default_result.scalar_one_or_none()
    if mc:
        api_key = _decrypt_api_key(mc.api_key_encrypted) if mc.api_key_encrypted else None
        params = mc.params or {}
        model_config = {
            "provider": mc.provider,
            "model_id": mc.model_id,
            "api_key": api_key,
            "base_url": params.get("base_url"),
            "temperature": params.get("temperature"),
        }

    optimized = await optimize_script(parsed, style=body.style, model_config=model_config)

    if optimized.get("status") == "error":
        raise HTTPException(status_code=500, detail=optimized.get("message", "Optimization failed"))

    version_result = await db.execute(
        select(Script).where(Script.note_id == note_id).order_by(Script.version.desc()).limit(1)
    )
    last_version = version_result.scalar_one_or_none()
    next_version = (last_version.version + 1) if last_version else 1

    script = Script(
        note_id=note_id,
        version=next_version,
        style=body.style,
        content=optimized,
    )
    db.add(script)
    note.status = "scripted"
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(script)
    return ScriptResponse.model_validate(script)


@router.post("/notes/{note_id}/materials")
async def generate_note_materials(note_id: int, body: MaterialGenRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    script_result = await db.execute(
        select(Script).where(Script.note_id == note_id).order_by(Script.version.desc()).limit(1)
    )
    script = script_result.scalar_one_or_none()
    if script is None:
        raise HTTPException(status_code=400, detail="No script found. Please run optimization first.")
    script_content = script.content if script else {}

    model_config = None
    img_mc = None
    if body.model_config_id is not None:
        mc_result = await db.execute(select(ModelConfig).where(ModelConfig.id == body.model_config_id))
        img_mc = mc_result.scalar_one_or_none()
    if img_mc is None:
        default_img = await db.execute(
            select(ModelConfig).where(ModelConfig.provider == "image", ModelConfig.is_default == True)
        )
        img_mc = default_img.scalar_one_or_none()
    if img_mc is None:
        # Try any image config
        any_img = await db.execute(
            select(ModelConfig).where(ModelConfig.provider == "image").limit(1)
        )
        img_mc = any_img.scalar_one_or_none()
    if img_mc:
        api_key = _decrypt_api_key(img_mc.api_key_encrypted) if img_mc.api_key_encrypted else None
        params = img_mc.params or {}
        model_config = {
            "provider": img_mc.provider,
            "model_id": img_mc.model_id,
            "api_key": api_key,
            "base_url": params.get("base_url"),
        }

    materials_data = await generate_materials(script_content, model_config=model_config, image_style=body.image_style)

    # Delete old image materials and save new ones in a single transaction
    await db.execute(delete(Material).where(Material.note_id == note_id, Material.type == "image"))

    saved = []
    for m in materials_data:
        material = Material(
            note_id=note_id,
            type=m.get("type", "image"),
            url=m.get("url"),
            local_path=m.get("local_path"),
            prompt=m.get("prompt"),
            meta_data=m.get("metadata"),
            duration=m.get("duration"),
        )
        db.add(material)
        saved.append(material)

    note.status = "materials_ready"
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    for m in saved:
        await db.refresh(m)
    return [MaterialResponse.model_validate(m) for m in saved]


@router.delete("/materials/{material_id}", status_code=204)
async def delete_material(material_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Material).where(Material.id == material_id))
    m = result.scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="Material not found")
    await db.delete(m)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise


@router.post("/materials/{material_id}/regenerate", response_model=MaterialResponse)
async def regenerate_material(material_id: int, body: RegenerateRequest = RegenerateRequest(), db: AsyncSession = Depends(get_db)):
    """Regenerate a single image material using its existing prompt and image model config."""
    from app.services.material_gen import _generate_ai_image

    result = await db.execute(select(Material).where(Material.id == material_id))
    m = result.scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="Material not found")
    if m.type != "image":
        raise HTTPException(status_code=400, detail="Only image materials can be regenerated")

    # Get segment info from metadata
    seg_id = (m.meta_data or {}).get("segment_id", 0)
    prompt = m.prompt or ""
    segment = {"id": seg_id, "text": "", "visual_hint": ""}

    # Resolve image model config — prefer body.model_config_id, then default, then any
    img_mc = None
    if body.model_config_id is not None:
        mc_result = await db.execute(select(ModelConfig).where(ModelConfig.id == body.model_config_id))
        img_mc = mc_result.scalar_one_or_none()
    if img_mc is None:
        img_result = await db.execute(
            select(ModelConfig).where(ModelConfig.provider == "image", ModelConfig.is_default == True)
        )
        img_mc = img_result.scalar_one_or_none()
    if img_mc is None:
        any_img = await db.execute(select(ModelConfig).where(ModelConfig.provider == "image").limit(1))
        img_mc = any_img.scalar_one_or_none()
    model_config = None
    if img_mc:
        api_key = _decrypt_api_key(img_mc.api_key_encrypted) if img_mc.api_key_encrypted else None
        params = img_mc.params or {}
        model_config = {
            "provider": img_mc.provider,
            "model_id": img_mc.model_id,
            "api_key": api_key,
            "base_url": params.get("base_url"),
        }

    new_img = await _generate_ai_image(segment, prompt, model_config)
    if new_img is None:
        raise HTTPException(status_code=500, detail="Image regeneration failed")

    # Update existing material
    m.url = new_img.get("url")
    m.local_path = new_img.get("local_path")
    m.prompt = new_img.get("prompt", m.prompt)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(m)
    return MaterialResponse.model_validate(m)


@router.post("/notes/{note_id}/tts")
async def generate_tts_audio(note_id: int, body: TtsRequest = TtsRequest(), db: AsyncSession = Depends(get_db)):
    """Generate TTS audio for each script segment."""
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    script_result = await db.execute(
        select(Script).where(Script.note_id == note_id).order_by(Script.version.desc()).limit(1)
    )
    script = script_result.scalar_one_or_none()
    if script is None:
        raise HTTPException(status_code=400, detail="No script found. Please run optimization first.")
    script_content = script.content if script else {}
    segments = script_content.get("segments", [])

    if not segments:
        raise HTTPException(status_code=400, detail="No segments in script")

    # Resolve voice: explicit param > default tts config > settings
    # Voice may contain a timbre suffix like "zh-TW-HsiaoChenNeural|anchor"
    voice = body.voice
    voice_timbre = None
    if voice and "|" in voice:
        voice, voice_timbre = voice.rsplit("|", 1)
    if not voice:
        tts_result = await db.execute(
            select(ModelConfig).where(ModelConfig.provider == "tts", ModelConfig.is_default == True)
        )
        tts_mc = tts_result.scalar_one_or_none()
        voice = tts_mc.model_id if tts_mc else settings.TTS_VOICE

    # Resolve TTS style: rate, pitch, volume
    # Voice-level timbre overrides take priority over tts_style
    TTS_STYLES = {
        "normal": {"rate": "+0%", "pitch": "+0Hz", "volume": "+0%"},
        "clear": {"rate": "-15%", "pitch": "+3Hz", "volume": "+15%"},
        "brisk": {"rate": "+20%", "pitch": "+1Hz", "volume": "+0%"},
        "gentle": {"rate": "-5%", "pitch": "-2Hz", "volume": "-5%"},
        "serious": {"rate": "-15%", "pitch": "-3Hz", "volume": "+5%"},
        "magnetic": {"rate": "-20%", "pitch": "-5Hz", "volume": "+10%"},
        # Voice-specific timbre presets
        "anchor": {"rate": "-20%", "pitch": "-3Hz", "volume": "+10%"},
        "intellectual": {"rate": "-10%", "pitch": "-2Hz", "volume": "+5%"},
        "crisp": {"rate": "-5%", "pitch": "+5Hz", "volume": "+5%"},
    }
    tts_style = voice_timbre or body.tts_style or "clear"
    style_params = TTS_STYLES.get(tts_style, TTS_STYLES["normal"])

    # Delete old audio materials (single transaction with new ones)
    await db.execute(delete(Material).where(Material.note_id == note_id, Material.type == "audio"))

    import edge_tts
    from pathlib import Path
    audio_dir = Path("storage/audio")
    audio_dir.mkdir(parents=True, exist_ok=True)

    # Build TTS tasks for parallel execution
    async def _generate_one_tts(seg: dict) -> Material | None:
        seg_id = seg.get("id", 0)
        text = seg.get("text", "").strip()
        if not text:
            return None
        out_path = audio_dir / f"note_{note_id}_seg_{seg_id}.mp3"
        try:
            communicate = edge_tts.Communicate(
                text, voice,
                rate=style_params["rate"],
                pitch=style_params["pitch"],
                volume=style_params["volume"],
            )
            await communicate.save(str(out_path))
            return Material(
                note_id=note_id,
                type="audio",
                local_path=str(out_path),
                prompt=text[:100],
                meta_data={"segment_id": seg_id, "voice": voice, "tts_style": tts_style},
            )
        except Exception:
            logger.exception("TTS failed for segment %s", seg_id)
            return None

    # Run all TTS tasks concurrently
    tts_results = await asyncio.gather(*[_generate_one_tts(seg) for seg in segments])
    saved = [m for m in tts_results if m is not None]
    for m in saved:
        db.add(m)

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    for m in saved:
        await db.refresh(m)
    return [MaterialResponse.model_validate(m) for m in saved]


@router.post("/notes/{note_id}/subtitles")
async def generate_note_subtitles(note_id: int, db: AsyncSession = Depends(get_db)):
    """Generate subtitle PNG materials for each script segment."""
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    script_result = await db.execute(
        select(Script).where(Script.note_id == note_id).order_by(Script.version.desc()).limit(1)
    )
    script = script_result.scalar_one_or_none()
    if script is None:
        raise HTTPException(status_code=400, detail="No script found. Please run optimization first.")
    script_content = script.content if script else {}

    # Delete old subtitle materials and save new ones in a single transaction
    await db.execute(delete(Material).where(Material.note_id == note_id, Material.type == "subtitle"))

    subtitle_results = await generate_subtitles(
        note_id=note_id,
        script=script_content,
    )

    saved = []
    for sub in subtitle_results:
        material = Material(
            note_id=note_id,
            type="subtitle",
            local_path=sub["phase_paths"][0] if sub["phase_paths"] else None,
            prompt=sub.get("text", "")[:100],
            meta_data={
                "segment_id": sub["segment_id"],
                "phases": sub.get("phases", []),
                "phase_paths": sub.get("phase_paths", []),
            },
        )
        db.add(material)
        saved.append(material)

    if saved:
        note.status = "subtitles_ready"
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    for m in saved:
        await db.refresh(m)
    return [MaterialResponse.model_validate(m) for m in saved]


@router.post("/notes/{note_id}/segment-videos")
async def generate_segment_videos(note_id: int, db: AsyncSession = Depends(get_db)):
    """Generate per-segment video clips: image + TTS audio + subtitle overlay via FFmpeg."""
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    script_result = await db.execute(
        select(Script).where(Script.note_id == note_id).order_by(Script.version.desc()).limit(1)
    )
    script = script_result.scalar_one_or_none()
    if script is None:
        raise HTTPException(status_code=400, detail="No script found. Please run optimization first.")
    script_content = script.content if script else {}

    # Load all materials
    materials_result = await db.execute(select(Material).where(Material.note_id == note_id))
    all_materials = [MaterialResponse.model_validate(m).model_dump() for m in materials_result.scalars().all()]

    # Load subtitle materials for overlay
    subtitle_materials = []
    for m in all_materials:
        if m.get("type") == "subtitle":
            meta = m.get("meta_data") or {}
            subtitle_materials.append({
                "segment_id": meta.get("segment_id", 0),
                "phases": meta.get("phases", []),
                "phase_paths": meta.get("phase_paths", []),
            })

    # Resolve TTS voice
    tts_result = await db.execute(
        select(ModelConfig).where(ModelConfig.provider == "tts", ModelConfig.is_default == True)
    )
    tts_mc = tts_result.scalar_one_or_none()
    voice = tts_mc.model_id if tts_mc else settings.TTS_VOICE

    # Delete old segment video materials and save new ones in a single transaction
    await db.execute(delete(Material).where(Material.note_id == note_id, Material.type == "video"))

    clips = await generate_segment_clips(
        note_id=note_id,
        materials=all_materials,
        script=script_content,
        voice=voice,
        subtitle_materials=subtitle_materials if subtitle_materials else None,
    )

    saved = []
    for clip in clips:
        material = Material(
            note_id=note_id,
            type="video",
            local_path=clip["local_path"],
            prompt=clip.get("text", "")[:100],
            meta_data={
                "segment_id": clip["segment_id"],
                "duration": clip["duration"],
                "kind": "segment_clip",
            },
            duration=clip["duration"],
        )
        db.add(material)
        saved.append(material)

    note.status = "ai_video_ready"
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    for m in saved:
        await db.refresh(m)
    return [MaterialResponse.model_validate(m) for m in saved]


@router.post("/notes/{note_id}/upload-video")
async def upload_source_video(note_id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Upload a source video and extract materials (keyframes + audio) from it."""
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    script_result = await db.execute(
        select(Script).where(Script.note_id == note_id).order_by(Script.version.desc()).limit(1)
    )
    script = script_result.scalar_one_or_none()
    if script is None:
        raise HTTPException(status_code=400, detail="No script found. Please run optimization first.")
    script_content = script.content if script else {}

    # Save uploaded video
    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large. Max size: {MAX_UPLOAD_SIZE // (1024*1024)}MB")
    filename = file.filename or "source.mp4"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}. Allowed: {', '.join(ALLOWED_VIDEO_EXTENSIONS)}")
    video_path = await save_upload_video(note_id, file_bytes, filename)

    # Delete old materials and save new ones in a single transaction
    await db.execute(delete(Material).where(Material.note_id == note_id))

    # Extract materials from the uploaded video
    materials_data = await generate_materials_from_video(video_path, script_content)

    saved = []
    for m in materials_data:
        material = Material(
            note_id=note_id,
            type=m.get("type", "image"),
            url=m.get("url"),
            local_path=m.get("local_path"),
            prompt=m.get("prompt"),
            meta_data=m.get("metadata"),
            duration=m.get("duration"),
        )
        db.add(material)
        saved.append(material)

    note.status = "materials_ready"
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    for m in saved:
        await db.refresh(m)
    return [MaterialResponse.model_validate(m) for m in saved]


@router.post("/notes/{note_id}/compose")
async def compose_note_video(note_id: int, body: ComposeRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    materials_result = await db.execute(select(Material).where(Material.note_id == note_id))
    materials = materials_result.scalars().all()

    script_result = await db.execute(
        select(Script).where(Script.note_id == note_id).order_by(Script.version.desc()).limit(1)
    )
    script = script_result.scalar_one_or_none()
    script_content = script.content if script else {}

    output = await compose_video(
        note_id=note_id,
        materials=[MaterialResponse.model_validate(m).model_dump() for m in materials],
        script=script_content,
        config={"resolution": body.resolution},
    )

    if output.get("status") == "error":
        raise HTTPException(status_code=500, detail=output.get("message", "Composition failed"))

    video = VideoOutput(
        note_id=note_id,
        url=output.get("url"),
        local_path=output.get("output_path"),
        resolution=body.resolution,
        meta_data=output,
    )
    db.add(video)
    note.status = "composed"
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(video)
    return VideoOutputResponse.model_validate(video)


def _get_model_config(model_config_id: int | None, db: AsyncSession) -> callable:
    """Return a coroutine that resolves model_config from an ID."""
    async def resolve():
        if model_config_id is None:
            return None
        mc_result = await db.execute(select(ModelConfig).where(ModelConfig.id == model_config_id))
        mc = mc_result.scalar_one_or_none()
        if not mc:
            return None
        api_key = _decrypt_api_key(mc.api_key_encrypted) if mc.api_key_encrypted else None
        params = mc.params or {}
        return {
            "provider": mc.provider,
            "model_id": mc.model_id,
            "api_key": api_key,
            "base_url": params.get("base_url"),
            "temperature": params.get("temperature"),
        }
    return resolve


@router.post("/notes/{note_id}/ai-video")
async def generate_ai_videos(note_id: int, body: ComposeRequest, db: AsyncSession = Depends(get_db)):
    """SSE endpoint that generates AI video clips per segment based on existing image materials.

    Steps: for each segment with an image, call img2video API → poll for completion → save video material.
    """
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    script_result = await db.execute(
        select(Script).where(Script.note_id == note_id).order_by(Script.version.desc()).limit(1)
    )
    script = script_result.scalar_one_or_none()
    if script is None:
        raise HTTPException(status_code=400, detail="No script found. Please run optimization first.")
    script_content = script.content if script else {}
    segments = script_content.get("segments", [])

    # Resolve video model config
    # Priority: body.model_config_id > dedicated provider=video config > provider=image config
    video_model_config = None

    if body.model_config_id is not None:
        mc_result = await db.execute(select(ModelConfig).where(ModelConfig.id == body.model_config_id))
        mc = mc_result.scalar_one_or_none()
        if mc:
            api_key = _decrypt_api_key(mc.api_key_encrypted) if mc.api_key_encrypted else None
            params = mc.params or {}
            video_model_config = {
                "provider": mc.provider,
                "model_id": mc.model_id,
                "api_key": api_key,
                "base_url": params.get("base_url"),
            }
    else:
        dedicated_video_cfg_result = await db.execute(select(ModelConfig).where(ModelConfig.provider == "video"))
        dedicated_video_cfg = dedicated_video_cfg_result.scalar_one_or_none()
        if dedicated_video_cfg:
            api_key = _decrypt_api_key(dedicated_video_cfg.api_key_encrypted) if dedicated_video_cfg.api_key_encrypted else None
            video_model_config = {
                "provider": dedicated_video_cfg.provider,
                "model_id": dedicated_video_cfg.model_id,
                "api_key": api_key,
                "base_url": (dedicated_video_cfg.params or {}).get("base_url"),
            }
        else:
            # Fall back to image provider config but use VIDEO_MODEL instead of image model_id
            video_cfg_result = await db.execute(select(ModelConfig).where(ModelConfig.provider == "image"))
            video_cfg = video_cfg_result.scalar_one_or_none()
            if video_cfg:
                api_key = _decrypt_api_key(video_cfg.api_key_encrypted) if video_cfg.api_key_encrypted else None
                video_model_config = {
                    "provider": "video",
                    "model_id": settings.VIDEO_MODEL,
                    "api_key": api_key,
                    "base_url": (video_cfg.params or {}).get("base_url"),
                }

    resolution = body.resolution or "1920x1080"

    # Load existing image materials to build segment→image map
    materials_result = await db.execute(select(Material).where(Material.note_id == note_id))
    existing_materials = materials_result.scalars().all()
    img_url_map: dict[int, str] = {}
    for m in existing_materials:
        if m.type == "image":
            sid = (m.meta_data or {}).get("segment_id")
            if sid is not None:
                img_url_map[sid] = m.url or m.local_path or ""

    async def event_stream():
        """SSE generator — uses its own DB session to survive client disconnects."""
        async with _get_note_lock(note_id):
            async with async_session() as sse_db:
                try:
                    has_video_api = bool(video_model_config and video_model_config.get("api_key"))
                    if not has_video_api:
                        yield f"data: {json.dumps({'phase': 'ai_video', 'step': 'skip', 'message': '未配置视频模型 API Key，跳过 AI 视频生成'}, ensure_ascii=False)}\n\n"
                        return

                    # Delete old video-type materials
                    old_vids = await sse_db.execute(select(Material).where(Material.note_id == note_id, Material.type == "video"))
                    for om in old_vids.scalars().all():
                        await sse_db.delete(om)

                    yield f"data: {json.dumps({'phase': 'ai_video', 'step': 'start', 'total': len(segments), 'current': 0, 'message': f'正在生成视频（共 {len(segments)} 段）...'}, ensure_ascii=False)}\n\n"

                    video_materials = []
                    for i, seg in enumerate(segments):
                        seg_id = seg.get("id")
                        img_ref = img_url_map.get(seg_id)

                        # Build image input for I2V: public URL or data URI for local files
                        img_input = None
                        if img_ref:
                            if img_ref.startswith("http"):
                                img_input = img_ref
                            elif os.path.isfile(img_ref):
                                from app.services.video_gen import _image_to_data_uri
                                img_input = _image_to_data_uri(img_ref)
                                if not img_input:
                                    logger.warning("Failed to convert local image to data URI for segment %s", seg_id)

                        seg_msg = seg.get("visual_hint") or seg.get("text", "")[:50]
                        yield f"data: {json.dumps({'phase': 'ai_video', 'step': 'progress', 'total': len(segments), 'current': i + 1, 'message': f'正在生成第 {i+1}/{len(segments)} 段视频：{seg_msg}...'}, ensure_ascii=False)}\n\n"

                        vid_result = await generate_segment_video(
                            segment=seg,
                            image_url=img_input,
                            model_config=video_model_config,
                            resolution=resolution,
                        )
                        if vid_result:
                            material = Material(
                                note_id=note_id,
                                type="video",
                                url=vid_result.get("url"),
                                local_path=vid_result.get("local_path"),
                                prompt=vid_result.get("prompt"),
                                meta_data=vid_result.get("metadata"),
                            )
                            sse_db.add(material)
                            video_materials.append(material)

                    if video_materials:
                        await sse_db.commit()
                        for vm in video_materials:
                            await sse_db.refresh(vm)

                    # Update note status
                    note_result = await sse_db.execute(select(Note).where(Note.id == note_id))
                    note_obj = note_result.scalar_one_or_none()
                    if note_obj:
                        note_obj.status = "ai_video_ready"
                        await sse_db.commit()

                    vid_count = len(video_materials)
                    yield f"data: {json.dumps({'phase': 'ai_video', 'step': 'done', 'total': len(segments), 'generated': vid_count, 'message': f'AI 视频生成完成：{vid_count} 段'}, ensure_ascii=False)}\n\n"

                except Exception as exc:
                    await sse_db.rollback()
                    logger.exception("AI video generation stream failed")
                    yield f"data: {json.dumps({'phase': 'ai_video', 'step': 'error', 'message': f'AI 视频生成失败：{str(exc)}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/notes/{note_id}/generate-video")
async def generate_video_stream(note_id: int, body: ComposeRequest, db: AsyncSession = Depends(get_db)):
    """SSE endpoint that generates video with progress updates.

    Steps: generate materials → generate AI videos per segment → compose final video.
    """
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    script_result = await db.execute(
        select(Script).where(Script.note_id == note_id).order_by(Script.version.desc()).limit(1)
    )
    script = script_result.scalar_one_or_none()
    if script is None:
        raise HTTPException(status_code=400, detail="No script found. Please run optimization first.")
    script_content = script.content if script else {}
    segments = script_content.get("segments", [])

    # Resolve model configs
    image_cfg_result = await db.execute(select(ModelConfig).where(ModelConfig.provider == "image"))
    image_cfg = image_cfg_result.scalar_one_or_none()
    image_model_config = None
    if image_cfg:
        api_key = _decrypt_api_key(image_cfg.api_key_encrypted) if image_cfg.api_key_encrypted else None
        image_model_config = {
            "provider": image_cfg.provider,
            "model_id": image_cfg.model_id,
            "api_key": api_key,
            "base_url": (image_cfg.params or {}).get("base_url"),
        }

    video_model_config = image_model_config  # same key, different model_id
    resolution = body.resolution or "1920x1080"

    async def event_stream():
        """SSE generator — uses its own DB session to survive client disconnects."""
        async with _get_note_lock(note_id):
            async with async_session() as sse_db:
                try:
                    # Phase 1: Generate materials (images + audio)
                    yield f"data: {json.dumps({'phase': 'materials', 'step': 'start', 'message': f'正在生成素材（{len(segments)} 段）...'}, ensure_ascii=False)}\n\n"

                    # Delete old materials
                    await sse_db.execute(delete(Material).where(Material.note_id == note_id))

                    materials_data = await generate_materials(script_content, model_config=image_model_config)
                    saved_materials = []
                    for m in materials_data:
                        material = Material(
                            note_id=note_id,
                            type=m.get("type", "image"),
                            url=m.get("url"),
                            local_path=m.get("local_path"),
                            prompt=m.get("prompt"),
                            meta_data=m.get("metadata"),
                            duration=m.get("duration"),
                        )
                        sse_db.add(material)
                        saved_materials.append(material)
                    note_obj = (await sse_db.execute(select(Note).where(Note.id == note_id))).scalar_one_or_none()
                    if note_obj:
                        note_obj.status = "materials_ready"
                    await sse_db.commit()
                    for m in saved_materials:
                        await sse_db.refresh(m)

                    img_count = len([m for m in materials_data if m.get("type") == "image"])
                    yield f"data: {json.dumps({'phase': 'materials', 'step': 'done', 'message': f'素材生成完成：{img_count} 张图片'}, ensure_ascii=False)}\n\n"

                    # Phase 2: Generate AI video for each segment
                    has_video_api = bool(video_model_config and video_model_config.get("api_key"))
                    video_materials = []

                    if has_video_api:
                        yield f"data: {json.dumps({'phase': 'ai_video', 'step': 'start', 'total': len(segments), 'current': 0, 'message': f'正在生成视频（共 {len(segments)} 段）...'}, ensure_ascii=False)}\n\n"

                        # Build image URL map for img2video
                        img_url_map: dict[int, str] = {}
                        for m in materials_data:
                            if m.get("type") == "image":
                                sid = (m.get("metadata") or {}).get("segment_id")
                                if sid is not None:
                                    img_url_map[sid] = m.get("url") or m.get("local_path")

                        for i, seg in enumerate(segments):
                            seg_id = seg.get("id")
                            img_url = img_url_map.get(seg_id)
                            # Convert local path to URL if needed
                            if img_url and not img_url.startswith("http"):
                                img_url = None  # AI video API needs public URL

                            seg_msg = seg.get("visual_hint") or seg.get("text", "")[:50]
                            yield f"data: {json.dumps({'phase': 'ai_video', 'step': 'progress', 'total': len(segments), 'current': i + 1, 'message': f'正在生成第 {i+1}/{len(segments)} 段视频：{seg_msg}...'}, ensure_ascii=False)}\n\n"

                            vid_result = await generate_segment_video(
                                segment=seg,
                                image_url=img_url,
                                model_config=video_model_config,
                                resolution=resolution,
                            )
                            if vid_result:
                                material = Material(
                                    note_id=note_id,
                                    type="video",
                                    url=vid_result.get("url"),
                                    local_path=vid_result.get("local_path"),
                                    prompt=vid_result.get("prompt"),
                                    meta_data=vid_result.get("metadata"),
                                )
                                sse_db.add(material)
                                video_materials.append(material)

                        if video_materials:
                            await sse_db.commit()
                            for vm in video_materials:
                                await sse_db.refresh(vm)

                        vid_count = len(video_materials)
                        yield f"data: {json.dumps({'phase': 'ai_video', 'step': 'done', 'message': f'AI 视频生成完成：{vid_count} 段'}, ensure_ascii=False)}\n\n"

                    # Phase 3: Compose final video
                    yield f"data: {json.dumps({'phase': 'compose', 'step': 'start', 'message': '正在合成最终视频...'}, ensure_ascii=False)}\n\n"

                    all_materials_result = await sse_db.execute(select(Material).where(Material.note_id == note_id))
                    all_materials = [MaterialResponse.model_validate(m).model_dump() for m in all_materials_result.scalars().all()]

                    output = await compose_video(
                        note_id=note_id,
                        materials=all_materials,
                        script=script_content,
                        config={"resolution": resolution},
                    )

                    if output.get("status") == "error":
                        yield f"data: {json.dumps({'phase': 'compose', 'step': 'error', 'message': output.get('message', '合成失败')}, ensure_ascii=False)}\n\n"
                        return

                    video = VideoOutput(
                        note_id=note_id,
                        url=output.get("url"),
                        local_path=output.get("output_path"),
                        resolution=resolution,
                        meta_data=output,
                    )
                    sse_db.add(video)
                    note_obj = (await sse_db.execute(select(Note).where(Note.id == note_id))).scalar_one_or_none()
                    if note_obj:
                        note_obj.status = "composed"
                    await sse_db.commit()
                    await sse_db.refresh(video)

                    duration = output.get("duration", 0)
                    yield f"data: {json.dumps({'phase': 'compose', 'step': 'done', 'message': f'视频合成完成！时长 {duration:.1f} 秒', 'video_id': video.id}, ensure_ascii=False)}\n\n"

                except Exception as exc:
                    await sse_db.rollback()
                    logger.exception("Video generation stream failed")
                    yield f"data: {json.dumps({'phase': 'error', 'message': f'生成失败：{str(exc)}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Slide (PPT-style) generation endpoints
# ---------------------------------------------------------------------------


@router.post("/notes/{note_id}/slides")
async def generate_note_slides(note_id: int, body: SlideGenRequest = SlideGenRequest(), db: AsyncSession = Depends(get_db)):
    """Generate PPT-style slides with AI backgrounds from the latest script for a note."""
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    script_result = await db.execute(
        select(Script).where(Script.note_id == note_id).order_by(Script.version.desc()).limit(1)
    )
    script = script_result.scalar_one_or_none()
    if script is None:
        raise HTTPException(status_code=400, detail="No script found. Please run optimization first.")
    script_content = script.content if script else {}

    # Resolve image model config
    img_mc = None
    if body.model_config_id is not None:
        mc_result = await db.execute(select(ModelConfig).where(ModelConfig.id == body.model_config_id))
        img_mc = mc_result.scalar_one_or_none()
    if img_mc is None:
        default_img = await db.execute(
            select(ModelConfig).where(ModelConfig.provider == "image", ModelConfig.is_default == True)
        )
        img_mc = default_img.scalar_one_or_none()
    if img_mc is None:
        any_img = await db.execute(
            select(ModelConfig).where(ModelConfig.provider == "image").limit(1)
        )
        img_mc = any_img.scalar_one_or_none()
    model_config = None
    if img_mc:
        api_key = _decrypt_api_key(img_mc.api_key_encrypted) if img_mc.api_key_encrypted else None
        params = img_mc.params or {}
        model_config = {
            "provider": img_mc.provider,
            "model_id": img_mc.model_id,
            "api_key": api_key,
            "base_url": params.get("base_url"),
            "image_style": body.image_style,  # Pass style for prompt enhancement
        }
        # For Gemini free model, prefer the key passed from frontend
        if body.gemini_api_key and model_config.get("model_id") in ("gemini-flash-image",):
            model_config["api_key"] = body.gemini_api_key

    # Fallback: no DB config but frontend passed a model_id (e.g. free models)
    if model_config is None and body.model_id:
        model_config = {
            "provider": "image",
            "model_id": body.model_id,
            "api_key": None,
            "base_url": None,
            "image_style": body.image_style,
        }
        if body.gemini_api_key and body.model_id == "gemini-flash-image":
            model_config["api_key"] = body.gemini_api_key

    # Resolve LLM config for image prompt generation
    llm_mc = None
    if body.llm_config_id is not None:
        llm_result = await db.execute(select(ModelConfig).where(ModelConfig.id == body.llm_config_id))
        llm_mc = llm_result.scalar_one_or_none()
    if llm_mc is None:
        default_llm = await db.execute(
            select(ModelConfig).where(ModelConfig.provider == "llm", ModelConfig.is_default == True)
        )
        llm_mc = default_llm.scalar_one_or_none()
    llm_config = None
    if llm_mc:
        api_key = _decrypt_api_key(llm_mc.api_key_encrypted) if llm_mc.api_key_encrypted else None
        params = llm_mc.params or {}
        llm_config = {
            "provider": llm_mc.provider,
            "model_id": llm_mc.model_id,
            "api_key": api_key,
            "base_url": params.get("base_url"),
            "temperature": params.get("temperature"),
        }

    # Delete old slide materials
    await db.execute(delete(Material).where(Material.note_id == note_id, Material.type == "slide"))

    output_format = body.output_format or "pptx"

    # Pre-check image API accessibility (skip for free models)
    free_model = model_config and model_config.get("model_id") and _is_free_model(model_config["model_id"])
    if model_config and model_config.get("api_key") and not free_model:
        try:
            precheck_url = f"{(model_config.get('base_url') or settings.IMAGE_BASE_URL).rstrip('/')}/images/generations"
            precheck_headers = {"Authorization": f"Bearer {model_config['api_key']}", "Content-Type": "application/json"}
            precheck_payload = {"model": model_config["model_id"], "prompt": "test", "image_size": "1024x1024", "num_inference_steps": 1}
            import httpx as _httpx
            async with _httpx.AsyncClient(timeout=15.0) as _client:
                _resp = await _client.post(precheck_url, json=precheck_payload, headers=precheck_headers)
                if _resp.status_code in (401, 402, 403):
                    try:
                        _detail = _resp.json().get("message", "")
                    except Exception:
                        _detail = ""
                    if _resp.status_code == 402 or "insufficient" in _detail.lower() or "余额" in _detail:
                        raise HTTPException(status_code=402, detail=f"图片模型 {model_config['model_id']} 余额不足，请充值后重试。当前账户余额为 0。")
                    raise HTTPException(status_code=403, detail=f"图片模型 {model_config['model_id']} 不可用：{_detail or '该模型未开启'}。请在 SiliconFlow 后台开启模型权限，或切换其他模型。")
        except HTTPException:
            raise
        except Exception:
            pass  # Network errors etc. are ok, will be caught during actual generation

    if output_format == "xiaohongshu":
        slides_result = await generate_xhs_images(
            script_content,
            note_id=note_id,
            image_style=body.image_style,
            model_config=model_config,
            llm_config=llm_config,
        )
        format_label = "小红书"
    else:
        slides_result = await generate_slides(
            script_content,
            note_id=note_id,
            image_style=body.image_style,
            model_config=model_config,
            llm_config=llm_config,
        )
        format_label = "PPT"

    # Save as a single Material entry
    material = Material(
        note_id=note_id,
        type="slide",
        local_path=slides_result.get("local_path"),
        prompt=f"{format_label} · {slides_result.get('page_count', 0)} 页",
        meta_data={
            "page_count": slides_result.get("page_count", 0),
            "has_ai_bg": slides_result.get("has_ai_bg", False),
            "output_format": output_format,
            "image_paths": slides_result.get("image_paths", []),
        },
    )
    db.add(material)

    note.status = "slides_ready"
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(material)
    return MaterialResponse.model_validate(material)


@router.get("/image-styles")
async def get_image_styles():
    """Return available image style presets with metadata for the frontend."""
    return {
        "styles": [
            {
                "key": key,
                "label": meta["label"],
                "icon": meta["icon"],
                "desc": meta["desc"],
            }
            for key, meta in STYLE_METADATA.items()
        ]
    }


# ============================================================
# Xiaohongshu (小红书) dedicated endpoints
# ============================================================

@router.get("/xhs/models")
async def get_xhs_models():
    """Return free image models available for Xiaohongshu generation with rich metadata."""
    return {
        "models": [
            {
                "id": model_id,
                "label": meta["label"],
                "description": meta["description"],
                "features": meta["features"],
                "speed": meta["speed"],
                "quality": meta["quality"],
                "best_for": meta["best_for"],
                "requires_key": meta["requires_key"],
                "icon": meta["icon"],
            }
            for model_id, meta in FREE_IMAGE_MODELS.items()
        ]
    }


@router.post("/xhs/generate")
async def generate_xhs_post(body: XhsGenRequest):
    """One-click Xiaohongshu post generation with free models.

    Flow: Content → Split pages → Template prompts → AI backgrounds → Render → ZIP
    No database config needed — works entirely with free models.
    """
    import zipfile
    import uuid
    import random
    from pathlib import Path

    model_id = body.model_id
    title = body.title
    content = body.content
    image_style = body.image_style or "realistic"
    session_id = uuid.uuid4().hex[:8]

    # Validate model
    if model_id not in FREE_IMAGE_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported model: {model_id}. Available: {list(FREE_IMAGE_MODELS.keys())}",
        )

    model_meta = FREE_IMAGE_MODELS[model_id]
    if model_meta.get("requires_key") and not body.gemini_api_key:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{model_meta['label']}' requires a Gemini API key. Get one free at aistudio.google.com",
        )

    # Build model_config from free model metadata (include image_style for Gemini style hints)
    model_config = {
        "model_id": model_id,
        "provider": model_meta["provider"],
        "model_name": model_meta["model_name"],
        "image_style": image_style,
    }
    if body.gemini_api_key:
        model_config["api_key"] = body.gemini_api_key
    elif model_meta["provider"] == "pollinations" and settings.POLLINATIONS_API_KEY:
        model_config["api_key"] = settings.POLLINATIONS_API_KEY

    # Split content into pages
    # Strategy: split by double newline for pages, single newline for heading/body within page
    raw_pages = [p.strip() for p in content.split("\n\n") if p.strip()]
    if not raw_pages:
        raw_pages = [content.strip()]

    # Limit to 10 pages max for reasonable generation time
    raw_pages = raw_pages[:10]

    # Build segment list compatible with rendering functions
    segments = []
    for page_text in raw_pages:
        lines = page_text.split("\n", 1)
        heading = lines[0].strip()
        page_body = lines[1].strip() if len(lines) > 1 else ""
        # Infer mood per page
        mood = _infer_emotion_atmosphere(page_text)
        segments.append({
            "heading": heading,
            "body": page_body,
            "text": page_text,
            "emotion": mood,
            "visual_hint": "",
        })

    # Build prompts from template (no LLM needed)
    prompts = _build_xhs_prompts_from_template(
        title=title,
        segments=segments,
        image_style=image_style,
        model_id=model_id,
    )
    cover_prompt = prompts[0]
    page_prompts = prompts[1:]

    # Ensure storage directory
    storage_path = Path("storage/slides")
    storage_path.mkdir(parents=True, exist_ok=True)

    # Generate cover background
    logger.info("Generating XHS cover with %s...", model_id)
    try:
        bg_path = await _generate_xhs_bg_image(
            prompt=cover_prompt,
            seg_id="cover",
            note_id=0,
            model_config=model_config,
        )
    except HTTPException:
        raise
    except Exception:
        bg_path = None

    # Generate content page backgrounds (sequential for stability, or parallel for speed)
    image_paths = []
    palette = random.choice(XHS_PALETTES)

    # Cover
    if bg_path and os.path.exists(bg_path):
        cover_out = str(storage_path / f"xhs_{session_id}_cover.png")
        _render_xhs_cover(
            title=title,
            subtitle=raw_pages[0][:30] if raw_pages else "",
            bg_image_path=bg_path if os.path.exists(bg_path) else None,
            palette=palette,
            out_path=cover_out,
        )
        if os.path.exists(cover_out):
            image_paths.append(cover_out)

    # Content pages
    total_pages = len(segments)
    for i, seg in enumerate(segments):
        page_num = i + 1
        prompt = page_prompts[i] if i < len(page_prompts) else ""
        palette = random.choice(XHS_PALETTES)

        try:
            seg_bg = await _generate_xhs_bg_image(
                prompt=prompt,
                seg_id=f"p{page_num}",
                note_id=0,
                model_config=model_config,
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("Failed to generate BG for page %d: %s", page_num, e)
            seg_bg = None

        out_path = str(storage_path / f"xhs_{session_id}_page_{page_num:02d}.png")
        result = _render_xhs_content(
            heading=seg.get("heading", ""),
            body=seg.get("body", ""),
            page_num=page_num,
            total_pages=total_pages,
            bg_image_path=seg_bg if seg_bg and os.path.exists(seg_bg) else None,
            palette=palette,
            out_path=out_path,
        )
        if result and os.path.exists(out_path):
            image_paths.append(out_path)

    # Pack into ZIP
    zip_path = str(storage_path / f"xhs_{session_id}_post.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for img_path in image_paths:
            zf.write(img_path, os.path.basename(img_path))

    return {
        "success": True,
        "format": "xiaohongshu",
        "page_count": len(image_paths),
        "image_paths": image_paths,
        "zip_path": zip_path,
        "model_used": model_meta["label"],
        "title": title,
    }
