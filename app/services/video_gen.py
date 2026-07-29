"""AI video generation service — supports SiliconFlow and Replicate as providers."""

import asyncio
import base64
import logging
import os
import tempfile
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

VIDEOS_DIR = Path("storage") / "videos"

# SiliconFlow supported image sizes
SIZE_MAP = {
    "1920x1080": "1280x720",
    "1280x720": "1280x720",
    "1080x1920": "720x1280",
    "720x1280": "720x1280",
    "960x960": "960x960",
}

# SiliconFlow models
SF_T2V_MODEL = "Wan-AI/Wan2.2-T2V-A14B"
SF_I2V_MODEL = "Wan-AI/Wan2.2-I2V-A14B"

# Replicate models
REPLICATE_T2V = "wan-video/wan-2.5-t2v-fast"
REPLICATE_I2V = "wan-video/wan-2.5-i2v-fast"


def _ensure_dirs() -> None:
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)


def _image_to_data_uri(path: str) -> str | None:
    """Convert a local image file to a data URI for the API."""
    try:
        with open(path, "rb") as f:
            data = f.read()
        ext = Path(path).suffix.lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext.lstrip("."), "image/png")
        return f"data:{mime};base64,{base64.b64encode(data).decode()}"
    except Exception:
        logger.exception("Failed to convert image to data URI: %s", path)
        return None


def _image_to_base64_file(path: str) -> str | None:
    """Convert a local image to a base64-encoded file URI for Replicate."""
    try:
        with open(path, "rb") as f:
            data = f.read()
        return base64.b64encode(data).decode()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# SiliconFlow video API
# ---------------------------------------------------------------------------

async def _sf_submit(prompt: str, model_config: dict, image_url: str | None, resolution: str) -> dict | None:
    api_key = model_config.get("api_key")
    base_url = model_config.get("base_url") or settings.VIDEO_BASE_URL
    if not api_key:
        return None

    url = f"{base_url.rstrip('/')}/video/submit"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    image_size = SIZE_MAP.get(resolution, "1280x720")
    has_image = bool(image_url)
    model_id = model_config.get("model_id") or (SF_I2V_MODEL if has_image else SF_T2V_MODEL)

    payload: dict = {"model": model_id, "prompt": prompt, "image_size": image_size}
    if has_image:
        payload["image"] = image_url

    logger.info("[SiliconFlow] submit model=%s size=%s has_image=%s", model_id, image_size, has_image)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.error("[SiliconFlow] submit failed (%s): %s", resp.status_code, resp.text[:300])
            resp.raise_for_status()
            return resp.json()
    except Exception:
        logger.exception("[SiliconFlow] submit error")
        return None


async def _sf_poll(request_id: str, model_config: dict, max_wait: int = 600, poll_interval: int = 10) -> dict | None:
    api_key = model_config.get("api_key")
    base_url = model_config.get("base_url") or settings.VIDEO_BASE_URL
    if not api_key:
        return None

    url = f"{base_url.rstrip('/')}/video/status"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    elapsed = 0
    while elapsed < max_wait:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json={"requestId": request_id}, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            status = data.get("status", "")
            if status in ("Succeed", "succeeded", "Success", "success", "Done", "done"):
                return data
            if status in ("Failed", "failed", "Error", "error", "Cancelled", "cancelled"):
                logger.error("[SiliconFlow] generation failed: %s", data)
                return None
        except Exception:
            logger.warning("[SiliconFlow] poll error, retrying...")
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    logger.error("[SiliconFlow] timed out after %ds", max_wait)
    return None


# ---------------------------------------------------------------------------
# Replicate video API
# ---------------------------------------------------------------------------

async def _replicate_run(prompt: str, model_config: dict, image_url: str | None, resolution: str) -> str | None:
    """Run a Replicate prediction and return the output video URL."""
    api_key = model_config.get("api_key") or settings.REPLICATE_API_TOKEN
    if not api_key:
        return None

    has_image = bool(image_url)
    model = model_config.get("model_id") or (REPLICATE_I2V if has_image else REPLICATE_T2V)

    # Determine aspect ratio
    if resolution in ("1080x1920", "720x1280"):
        aspect_ratio = "9:16"
    else:
        aspect_ratio = "16:9"

    input_data: dict = {
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
    }
    if has_image:
        input_data["image"] = image_url

    logger.info("[Replicate] run model=%s aspect=%s has_image=%s", model, aspect_ratio, has_image)

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # Create prediction (async)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.replicate.com/v1/predictions",
                headers=headers,
                json={"model": model, "input": input_data},
            )
            if resp.status_code not in (200, 201):
                logger.error("[Replicate] create failed (%s): %s", resp.status_code, resp.text[:300])
                return None
            data = resp.json()
            prediction_id = data.get("id")
            get_url = data.get("urls", {}).get("get")
            if not prediction_id or not get_url:
                logger.error("[Replicate] no prediction id in response")
                return None
    except Exception:
        logger.exception("[Replicate] create error")
        return None

    # Poll for completion
    elapsed = 0
    max_wait = 600
    poll_interval = 10
    while elapsed < max_wait:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(get_url, headers={"Authorization": f"Bearer {api_key}"})
                resp.raise_for_status()
                data = resp.json()
            status = data.get("status", "")
            if status == "succeeded":
                output = data.get("output")
                if isinstance(output, str):
                    return output
                if isinstance(output, list) and output:
                    return output[0] if isinstance(output[0], str) else output[0].get("url")
                logger.error("[Replicate] unexpected output format: %s", type(output))
                return None
            if status in ("failed", "canceled", "cancelled"):
                logger.error("[Replicate] prediction failed: %s", data.get("error"))
                return None
        except Exception:
            logger.warning("[Replicate] poll error, retrying...")

    logger.error("[Replicate] timed out after %ds", max_wait)
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def generate_segment_video(
    segment: dict,
    image_url: str | None = None,
    model_config: dict | None = None,
    resolution: str = "1920x1080",
) -> dict | None:
    """Generate a video for a single segment using AI video model.

    Tries SiliconFlow first, falls back to Replicate if SiliconFlow fails.
    Returns dict with type, url, local_path, prompt, metadata or None on failure.
    """
    seg_id = int(segment.get("id", 0))
    text = segment.get("text", "")
    visual_hint = segment.get("visual_hint", "")
    emotion = segment.get("emotion", "neutral")

    prompt_parts = []
    if visual_hint:
        prompt_parts.append(visual_hint)
    if text:
        prompt_parts.append(f"Narration: {text[:100]}")
    emotion_map = {
        "inspiring": "uplifting and motivational",
        "positive": "bright and cheerful",
        "neutral": "calm and balanced",
    }
    prompt_parts.append(f"Mood: {emotion_map.get(emotion, 'calm and balanced')}")
    prompt = ", ".join(prompt_parts) if prompt_parts else "A calm scenic video"

    cfg = model_config or {}
    video_url = None
    provider_used = None

    # --- Try SiliconFlow ---
    sf_api_key = cfg.get("api_key") or settings.VIDEO_API_KEY or settings.IMAGE_API_KEY
    if sf_api_key and cfg.get("base_url", "").find("siliconflow") >= 0 or (not cfg.get("base_url") and sf_api_key):
        submit_result = await _sf_submit(prompt, cfg, image_url, resolution)
        if submit_result:
            request_id = submit_result.get("requestId") or submit_result.get("request_id")
            if request_id:
                logger.info("[SiliconFlow] segment %s submitted, requestId=%s", seg_id, request_id)
                result = await _sf_poll(request_id, cfg)
                if result:
                    results = result.get("results", {})
                    videos = results.get("videos", [])
                    if videos and isinstance(videos, list):
                        video_url = videos[0].get("url")
                    if not video_url:
                        output = result.get("output")
                        if isinstance(output, list) and output:
                            video_url = output[0] if isinstance(output[0], str) else output[0].get("url")
                        elif isinstance(output, str):
                            video_url = output
                        else:
                            video_url = result.get("video", {}).get("url")
                    if video_url:
                        provider_used = "siliconflow"
                else:
                    logger.warning("[SiliconFlow] segment %s polling failed, trying Replicate fallback", seg_id)
            else:
                logger.warning("[SiliconFlow] no requestId in response for segment %s", seg_id)
        else:
            logger.warning("[SiliconFlow] submit failed for segment %s, trying Replicate fallback", seg_id)

    # --- Try Replicate ---
    if not video_url:
        rep_api_key = settings.REPLICATE_API_TOKEN
        if rep_api_key:
            rep_cfg = {"api_key": rep_api_key, "model_id": REPLICATE_I2V if image_url else REPLICATE_T2V}
            rep_url = await _replicate_run(prompt, rep_cfg, image_url, resolution)
            if rep_url:
                video_url = rep_url
                provider_used = "replicate"

    if not video_url:
        logger.error("All video providers failed for segment %s", seg_id)
        return None

    # Download video
    _ensure_dirs()
    out_path = VIDEOS_DIR / f"segment_{seg_id}.mp4"
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(video_url)
            resp.raise_for_status()
            out_path.write_bytes(resp.content)
    except Exception:
        logger.exception("Failed to download video for segment %s", seg_id)
        return None

    logger.info("Video downloaded for segment %s: %s (%d bytes) via %s", seg_id, out_path, out_path.stat().st_size, provider_used)
    return {
        "type": "video",
        "url": video_url,
        "local_path": str(out_path),
        "prompt": prompt,
        "metadata": {
            "segment_id": seg_id,
            "kind": "ai_video",
            "provider": provider_used,
        },
    }
