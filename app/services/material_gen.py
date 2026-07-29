"""Material generation service for video production.

Generates AI images for each video segment, with support for
both paid models (SiliconFlow) and free models (Pollinations.ai, Gemini).
"""

import asyncio
import logging
import os
import textwrap
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException

import httpx
from PIL import Image, ImageDraw, ImageFont

from app.config import settings

# Import quality helpers from slide_gen for consistent prompt quality
try:
    from app.services.slide_gen import QUALITY_SUFFIX, NEGATIVE_PROMPT, SLIDE_STYLE_MAP, _extract_gemini_image_data
except ImportError:
    QUALITY_SUFFIX = "masterpiece, best quality, highly detailed, professional, sharp focus"
    NEGATIVE_PROMPT = "no text, no letters, no watermarks, no logos, no low quality, no blurry"
    SLIDE_STYLE_MAP = {}
    _extract_gemini_image_data = None  # type: ignore

# Reuse slide_gen's rich 12-style map (replaces the old 5-style IMAGE_STYLE_MAP)
IMAGE_STYLE_MAP = SLIDE_STYLE_MAP if SLIDE_STYLE_MAP else {
    "realistic": "highly realistic, photorealistic, detailed real-world photography, natural lighting, 8k",
    "comic": "simple comic strip style, black and white line art, minimalist ink drawing, hand-drawn sketch",
    "illustration": "colorful digital illustration, flat design, clean vector style, modern graphic art",
    "anime": "anime style, cel shading, vibrant colors, Japanese animation aesthetic",
    "watercolor": "watercolor painting, soft brush strokes, muted pastel tones, artistic wash effect",
    "minimal": "minimalist design, clean geometric composition, smooth subtle gradients, negative space",
    "cinematic": "cinematic film still, golden hour lighting, shallow depth of field, film grain",
    "dreamy": "ethereal dreamy atmosphere, soft glow, pastel color palette, hazy morning light",
    "vintage": "vintage film photography, warm sepia tones, film grain texture, nostalgic atmosphere",
    "cyberpunk": "cyberpunk aesthetic, neon lights, holographic reflections, futuristic cityscape",
    "nature": "lush nature landscape, golden sunlight through leaves, organic textures, botanical details",
    "abstract": "abstract fluid art, swirling organic shapes, rich jewel tones, marble texture",
}

logger = logging.getLogger(__name__)

STORAGE_ROOT = Path("storage")
CARDS_DIR = STORAGE_ROOT / "cards"
IMAGES_DIR = STORAGE_ROOT / "images"

CARD_WIDTH = 1920
CARD_HEIGHT = 1080
CARD_BG_COLOR = (255, 255, 255)
CARD_TEXT_COLOR = (30, 30, 30)
CARD_FONT_SIZE = 64
CARD_LINE_SPACING = 20
CARD_MARGIN = 120

MUSIC_CATALOG: dict[str, list[dict]] = {
    "inspiring": [
        {"title": "Epic Uplifting Orchestral", "duration": 60},
        {"title": "Motivational Piano Build", "duration": 45},
        {"title": "Cinematic Rise and Shine", "duration": 60},
    ],
    "positive": [
        {"title": "Happy Acoustic Morning", "duration": 50},
        {"title": "Bright Ukulele Smile", "duration": 40},
        {"title": "Cheerful Corporate Pop", "duration": 55},
    ],
    "neutral": [
        {"title": "Calm Ambient Pad", "duration": 60},
        {"title": "Soft Study Background", "duration": 50},
        {"title": "Gentle Lo-Fi Chill", "duration": 45},
    ],
    "calm": [
        {"title": "Calm Ambient Pad", "duration": 60},
        {"title": "Soft Study Background", "duration": 50},
        {"title": "Gentle Lo-Fi Chill", "duration": 45},
    ],
    "melancholy": [
        {"title": "Sad Piano Reflection", "duration": 55},
        {"title": "Mellow Strings Emotion", "duration": 50},
        {"title": "Nostalgic Acoustic", "duration": 45},
    ],
    "dramatic": [
        {"title": "Intense Orchestral Tension", "duration": 50},
        {"title": "Dark Cinematic Drums", "duration": 45},
        {"title": "Suspense Thriller Pad", "duration": 55},
    ],
    "energetic": [
        {"title": "Upbeat Electronic Drive", "duration": 50},
        {"title": "Fast Rock Energy", "duration": 45},
        {"title": "Pumping Bass Drop", "duration": 55},
    ],
    "reflective": [
        {"title": "Soft Piano Contemplation", "duration": 55},
        {"title": "Gentle Rain Ambient", "duration": 60},
        {"title": "Thoughtful Strings", "duration": 50},
    ],
}


def _ensure_dirs() -> None:
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def _build_visual_prompt(segment: dict, style: str, image_style: str | None = None) -> str:
    """Build a rich AI image prompt from segment metadata.

    Used as fallback when LLM doesn't provide an image_prompt in the script.
    Combines visual_hint, emotion, style, and image_style into a quality prompt.
    """
    visual_hint = segment.get("visual_hint", "")
    emotion = segment.get("emotion", "neutral")

    # Emotion → visual atmosphere mapping
    emotion_atmosphere = {
        "inspiring": "uplifting atmosphere, warm golden light rays, aspirational mood, expansive composition",
        "positive": "bright cheerful atmosphere, soft natural daylight, warm color temperature, hopeful mood",
        "neutral": "calm balanced atmosphere, diffused soft lighting, neutral color palette, serene composition",
        "melancholy": "somber reflective mood, cool blue tones, rainy or overcast lighting, introspective atmosphere",
        "dramatic": "intense dramatic atmosphere, high contrast chiaroscuro lighting, deep shadows, cinematic tension",
        "energetic": "dynamic energetic atmosphere, vibrant saturated colors, motion blur, exciting composition",
        "reflective": "thoughtful contemplative mood, soft window light, muted earth tones, quiet atmosphere",
    }

    # Video style → visual direction
    style_direction = {
        "knowledge": "educational visual, clean organized composition, professional and clear",
        "story": "cinematic storytelling scene, narrative visual, evocative atmosphere",
        "checklist": "clean infographic style, structured layout, professional presentation",
    }

    parts = []

    # 1. Main subject from visual_hint (the core of the image)
    if visual_hint:
        parts.append(visual_hint)

    # 2. Style direction based on video type
    if style in style_direction:
        parts.append(style_direction[style])

    # 3. Rich image style from 12-style system
    if image_style and image_style in IMAGE_STYLE_MAP:
        parts.append(IMAGE_STYLE_MAP[image_style])
    else:
        parts.append(IMAGE_STYLE_MAP.get("realistic", "photorealistic"))

    # 4. Emotion atmosphere
    if emotion in emotion_atmosphere:
        parts.append(emotion_atmosphere[emotion])

    # 5. Quality suffix
    parts.append(QUALITY_SUFFIX)

    return ", ".join(parts)


async def _generate_text_card(segment: dict) -> dict | None:
    seg_id = int(segment.get("id", 0))
    text = segment.get("text", "")
    if not text:
        return None
    try:
        # Run PIL operations in a thread to avoid blocking the event loop
        def _render():
            img = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), CARD_BG_COLOR)
            draw = ImageDraw.Draw(img)
            font = _load_font(CARD_FONT_SIZE)
            max_chars_per_line = int((CARD_WIDTH - 2 * CARD_MARGIN) / (CARD_FONT_SIZE * 0.55))
            wrapped = textwrap.fill(text, width=max_chars_per_line)
            lines = wrapped.split("\n")
            line_height = CARD_FONT_SIZE + CARD_LINE_SPACING
            total_text_height = len(lines) * line_height - CARD_LINE_SPACING
            y_start = (CARD_HEIGHT - total_text_height) // 2
            for i, line in enumerate(lines):
                bbox = draw.textbbox((0, 0), line, font=font)
                line_width = bbox[2] - bbox[0]
                x = (CARD_WIDTH - line_width) // 2
                y = y_start + i * line_height
                draw.text((x, y), line, fill=CARD_TEXT_COLOR, font=font)
            out_path = CARDS_DIR / f"segment_{seg_id}.png"
            img.save(str(out_path), "PNG")
            return {
                "type": "image", "url": None, "local_path": str(out_path),
                "prompt": "text card", "metadata": {"segment_id": seg_id, "kind": "text_card"},
            }
        return await asyncio.to_thread(_render)
    except Exception:
        logger.exception("Failed to generate text card for segment %s", seg_id)
        return None


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _get_optimal_inference_steps(model_id: str, default: int = 25) -> int:
    """Return optimal inference steps for known image models.

    Tuned for quality — slightly higher than minimal values to ensure good output.
    """
    m = model_id.lower()
    if "schnell" in m:
        return 4       # FLUX.1-schnell: 1-4 steps is optimal
    if "lightning" in m:
        return 6       # SDXL-Lightning: 4-8, 6 gives better quality
    if "flux" in m and "pro" in m:
        return 28      # FLUX.1-pro: needs more steps
    if "flux" in m and "dev" in m:
        return 25      # FLUX.1-dev: 20-50, 25 is sweet spot (was 28, overkill)
    if "flux" in m:
        return 20
    if "kolors" in m:
        return 28      # Kolors: quality improves up to 28 steps
    if "qwen-image" in m or "z-image" in m or "ernie" in m:
        return 25      # Qwen-Image / Z-Image / ERNIE: 25 for quality
    if "sd3" in m or "stable-diffusion-3" in m:
        return 28      # SD3.x needs more steps for quality
    if "turbo" in m:
        return 10      # Turbo models: 8-12, 10 gives better quality
    if "playground" in m:
        return 30      # Playground v2.5: benefits from more steps
    if "sdxl" in m:
        return 25      # SDXL base: 20-30 sweet spot
    if "sd" in m and "xl" not in m:
        return 25      # SD 1.5/2.x: 20-30
    return default


def _get_guidance_scale(model_id: str) -> float | None:
    """Return optimal CFG guidance scale for the model, or None if not applicable.

    Flow-matching models (FLUX, SD3) don't use classifier-free guidance.
    Diffusion models (SD, SDXL) do.
    """
    m = model_id.lower()
    # Flow-matching models — guidance_scale is not applicable
    if any(x in m for x in ("flux", "sd3", "stable-diffusion-3", "schnell", "lightning")):
        return None
    # SD/SDXL-based models
    if any(x in m for x in ("sd", "sdxl", "stable-diffusion", "turbo")):
        return 7.5
    # Kolors (based on SDXL)
    if "kolors" in m:
        return 7.5
    # Default for unknown diffusion models
    return 7.0


def _enhance_image_prompt(prompt: str, model_id: str, image_style: str | None = None) -> str:
    """Enrich the prompt with quality keywords and model-specific optimizations.

    Different models respond better to different prompt structures:
    - FLUX: Benefits from descriptive, natural language prompts
    - SD/SDXL: Benefits from comma-separated keyword prompts
    - Kolors: Supports Chinese + English mixed prompts
    """
    m = model_id.lower()

    # Always add quality suffix for paid models
    if "pollinations" not in m and "gemini" not in m:
        prompt = f"{prompt}, {QUALITY_SUFFIX}"

    # FLUX models: keep natural language, add composition hints
    if "flux" in m:
        # FLUX does well with natural language, just add negative space hints
        if "negative space" not in prompt.lower():
            prompt = f"{prompt}, clean negative space, balanced composition"

    # SD-based models: optimize keyword density
    if any(x in m for x in ("sd", "sdxl", "stable-diffusion", "turbo", "kolors")):
        # SD models prefer detailed keyword chains
        # Ensure key quality markers are present
        markers = ["detailed", "sharp", "high resolution"]
        for marker in markers:
            if marker not in prompt.lower():
                prompt = f"{prompt}, {marker}"

    # Kolors: supports Chinese, make sure prompt is rich
    if "kolors" in m and len(prompt) < 80:
        # Kolors works best with detailed prompts
        prompt = f"{prompt}, 4k, masterpiece, exquisite detail, professional photography"

    return prompt


def _get_negative_prompt(model_id: str) -> str | None:
    """Return model-appropriate negative prompt, or None if not supported."""
    m = model_id.lower()

    # Pollinations and Gemini handle negative prompts differently (in their own functions)
    if "pollinations" in m or "gemini" in m:
        return None

    # Universal fallback — matches NEGATIVE_PROMPT from slide_gen
    return (
        "no text, no letters, no numbers, no watermarks, no signatures, "
        "no logos, no people faces in foreground, no clutter, no low quality, "
        "no blurry, no distorted, no ugly, no deformed, no bad anatomy, "
        "no extra limbs, no disfigured, no poorly drawn, no out of frame"
    )


async def _generate_ai_image(segment: dict, prompt: str, model_config: dict | None = None) -> dict | None:
    """Generate image via free models (Pollinations/Gemini) or SiliconFlow API."""
    seg_id = int(segment.get("id", 0))

    cfg = model_config or {}
    api_key = cfg.get("api_key") or settings.IMAGE_API_KEY
    base_url = cfg.get("base_url") or settings.IMAGE_BASE_URL
    model_id = cfg.get("model_id") or settings.IMAGE_MODEL

    # --- Pollinations.ai free model ---
    if "pollinations" in model_id.lower():
        result = await _generate_image_pollinations(prompt, seg_id, model_id, model_config)
        return result

    # --- Gemini free model ---
    if "gemini" in model_id.lower() or "flash-image" in model_id.lower():
        result = await _generate_image_gemini(prompt, seg_id, model_id, model_config)
        return result

    # Legacy: REPLICATE_API_KEY
    if not api_key and settings.REPLICATE_API_KEY:
        return await _generate_ai_image_replicate(segment, prompt)

    if not api_key:
        logger.debug("No IMAGE_API_KEY, skipping AI image generation")
        return None

    try:
        # SiliconFlow / OpenAI-compatible image generation endpoint
        url = f"{base_url.rstrip('/')}/images/generations"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Enhance prompt for current model
        enhanced_prompt = _enhance_image_prompt(prompt, model_id)

        steps = _get_optimal_inference_steps(model_id)
        guidance = _get_guidance_scale(model_id)
        neg_prompt = _get_negative_prompt(model_id)

        payload: dict = {
            "model": model_id,
            "prompt": enhanced_prompt,
            "image_size": "1920x1080",
            "num_inference_steps": steps,
        }

        # Add negative_prompt for supported models
        if neg_prompt:
            payload["negative_prompt"] = neg_prompt

        # Add guidance_scale for diffusion models (skip flow-matching models)
        if guidance is not None:
            payload["guidance_scale"] = guidance

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code in (401, 402, 403):
                try:
                    _msg = resp.json().get("message", "")
                except Exception:
                    _msg = ""
                if resp.status_code == 402 or "insufficient" in _msg.lower() or "余额" in _msg:
                    logger.error("Image model %s returned %s: %s", model_id, resp.status_code, _msg)
                    raise HTTPException(status_code=402, detail=f"图片模型 {model_id} 余额不足，请充值后重试")
                logger.error("Image model %s returned %s: %s", model_id, resp.status_code, _msg)
                raise HTTPException(status_code=resp.status_code, detail=f"图片模型 {model_id} 不可用：{_msg or '模型未开启'}")
            resp.raise_for_status()
            data = resp.json()

        # Parse response: {"images": [{"url": "..."}]}
        image_url = None
        images = data.get("images", [])
        if images and isinstance(images, list):
            image_url = images[0].get("url")
        elif data.get("data"):
            # OpenAI format: {"data": [{"url": "..."}]}
            image_url = data["data"][0].get("url")

        if not image_url:
            logger.warning("No image URL returned for segment %s", seg_id)
            return None

        out_path = IMAGES_DIR / f"segment_{seg_id}.png"
        async with httpx.AsyncClient(timeout=60.0) as client:
            img_resp = await client.get(image_url)
            img_resp.raise_for_status()
            out_path.write_bytes(img_resp.content)

        return {
            "type": "image", "url": image_url, "local_path": str(out_path),
            "prompt": prompt, "metadata": {"segment_id": seg_id, "kind": "ai_generated"},
        }
    except HTTPException:
        raise  # Let 403 errors bubble up to caller
    except Exception:
        logger.exception("Failed to generate AI image for segment %s", seg_id)
        return None


async def _generate_ai_image_replicate(segment: dict, prompt: str) -> dict | None:
    """Fallback: Generate image via Replicate FLUX.1-schnell."""
    seg_id = int(segment.get("id", 0))
    try:
        url = "https://api.replicate.com/v1/models/black-forest-labs/flux-1-schnell/predictions"
        headers = {
            "Authorization": f"Bearer {settings.REPLICATE_API_KEY}",
            "Content-Type": "application/json",
        }
        enhanced_prompt = _enhance_image_prompt(prompt, "flux-schnell")
        payload = {
            "input": {
                "prompt": enhanced_prompt,
                "num_outputs": 1,
                "aspect_ratio": "16:9",
                "output_format": "png",
                "output_quality": 90,
            },
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        image_url = None
        output = data.get("output")
        if isinstance(output, list) and output:
            image_url = output[0]
        elif isinstance(output, str):
            image_url = output
        else:
            # Poll for result
            get_url = data.get("urls", {}).get("get")
            if get_url:
                for _ in range(60):
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        r = await client.get(get_url, headers=headers)
                        r.raise_for_status()
                        d = r.json()
                    if d.get("status") == "succeeded":
                        out = d.get("output")
                        if isinstance(out, list) and out:
                            image_url = out[0]
                        elif isinstance(out, str):
                            image_url = out
                        break
                    if d.get("status") in ("failed", "canceled"):
                        break
                    import asyncio
                    await asyncio.sleep(2)

        if not image_url:
            return None

        out_path = IMAGES_DIR / f"segment_{seg_id}.png"
        async with httpx.AsyncClient(timeout=60.0) as client:
            img_resp = await client.get(image_url)
            img_resp.raise_for_status()
            out_path.write_bytes(img_resp.content)

        return {
            "type": "image", "url": image_url, "local_path": str(out_path),
            "prompt": prompt, "metadata": {"segment_id": seg_id, "kind": "ai_generated"},
        }
    except Exception:
        logger.exception("Replicate image generation failed for segment %s", seg_id)
        return None


# ===========================================================================
# Free image generation APIs (Pollinations.ai + Google Gemini)
# ===========================================================================

POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"


async def _generate_image_pollinations(
    prompt: str,
    seg_id: int,
    model_id: str = "",
    model_config: dict | None = None,
) -> dict | None:
    """Generate image using Pollinations.ai free API (no key required)."""
    try:
        # Map model_id to Pollinations model name
        model_map = {
            "pollinations-flux": "flux",
            "pollinations-turbo": "turbo",
            "pollinations-flux-realism": "flux-realism",
        }
        model_name = model_map.get(model_id, "flux")

        # Enhance prompt with quality suffix (negative handled via query param)
        enhanced_prompt = f"{prompt}, {QUALITY_SUFFIX}"
        encoded_prompt = quote(enhanced_prompt)

        params = {
            "width": "1920",
            "height": "1080",
            "model": model_name,
            "nologo": "true",
            "enhance": "true",
        }

        # Flux models support a dedicated negative prompt parameter
        flux_models = {"flux", "flux-realism"}
        if model_name in flux_models:
            params["negative"] = quote(NEGATIVE_PROMPT)

        cfg = model_config or {}
        pollinations_key = cfg.get("pollinations_key") or getattr(settings, "POLLINATIONS_API_KEY", "") or ""
        if pollinations_key:
            params["key"] = pollinations_key

        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{POLLINATIONS_BASE}/{encoded_prompt}?{param_str}"

        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning("Pollinations.ai returned %d for segment %s", resp.status_code, seg_id)
                return None

            out_path = IMAGES_DIR / f"segment_{seg_id}.png"
            out_path.write_bytes(resp.content)

        image_url = str(url)
        return {
            "type": "image", "url": image_url, "local_path": str(out_path),
            "prompt": prompt, "metadata": {"segment_id": seg_id, "kind": "ai_generated", "model": "pollinations"},
        }
    except Exception:
        logger.exception("Pollinations.ai generation failed for segment %s", seg_id)
        return None


async def _generate_image_gemini(
    prompt: str,
    seg_id: int,
    model_id: str = "",
    model_config: dict | None = None,
) -> dict | None:
    """Generate image using Google Gemini 2.5 Flash Image (500 free/day).

    Uses the official Gemini generateContent API:
    POST https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent
    """
    cfg = model_config or {}
    api_key = cfg.get("api_key") or getattr(settings, "GEMINI_API_KEY", "") or ""
    if not api_key:
        return None

    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        }

        full_prompt = (
            f"Professional photography, cinematic composition, {prompt}, "
            f"{QUALITY_SUFFIX}, {NEGATIVE_PROMPT}, "
            f"high quality, 16:9 wide aspect ratio"
        )

        body = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=body, headers=headers)
            if resp.status_code in (429, 403):
                logger.warning(
                    "Gemini API rate limited for segment %s: %d",
                    seg_id, resp.status_code,
                )
                return None
            if resp.status_code != 200:
                logger.warning(
                    "Gemini API returned %d for seg %s: %s",
                    resp.status_code, seg_id, resp.text[:300],
                )
                return None
            data = resp.json()

        # Extract image using the shared response parser
        image_data = _extract_gemini_image_data(data)

        if not image_data:
            logger.warning("Gemini returned no image for segment %s", seg_id)
            return None

        out_path = IMAGES_DIR / f"segment_{seg_id}.png"
        out_path.write_bytes(image_data)

        return {
            "type": "image", "url": None, "local_path": str(out_path),
            "prompt": prompt,
            "metadata": {
                "segment_id": seg_id,
                "kind": "ai_generated",
                "model": "gemini",
            },
        }
    except Exception:
        logger.exception("Gemini generation failed for segment %s", seg_id)
        return None


def _match_music(mood: str) -> list[dict]:
    mood = (mood or "neutral").lower()
    candidates = MUSIC_CATALOG.get(mood, MUSIC_CATALOG["neutral"])
    results = []
    for i, track in enumerate(candidates, start=1):
        results.append({
            "type": "audio", "url": None, "local_path": None,
            "prompt": f"{track['title']} ({mood} background music)",
            "metadata": {"mood": mood, "candidate_index": i, "title": track["title"], "duration": track["duration"]},
        })
    return results


async def generate_materials(script: dict, model_config: dict | None = None, image_style: str | None = None) -> list:
    _ensure_dirs()
    materials: list[dict] = []
    segments = script.get("segments", [])
    style = script.get("style", "knowledge")
    music_mood = script.get("music_mood", "neutral")

    for segment in segments:
        seg_id = segment.get("id", 0)

        # Priority 1: LLM-generated inline image_prompt (highest quality)
        prompt = segment.get("image_prompt", "").strip()

        # Priority 2: Build from visual_hint + style metadata
        if not prompt:
            visual_hint = segment.get("visual_hint", "")
            if visual_hint:
                prompt = _build_visual_prompt(segment, style, image_style)
            else:
                # No visual info at all → go straight to text card
                logger.info("Segment %s has no visual info, generating text card", seg_id)
                card = await _generate_text_card(segment)
                if card:
                    materials.append(card)
                continue

        # Try AI image generation
        ai_img = await _generate_ai_image(segment, prompt, model_config)
        if ai_img:
            materials.append(ai_img)
            continue

        # AI image failed → fallback to text card (never leave a gap)
        logger.info("AI image failed for segment %s, falling back to text card", seg_id)
        card = await _generate_text_card(segment)
        if card:
            materials.append(card)

    return materials
