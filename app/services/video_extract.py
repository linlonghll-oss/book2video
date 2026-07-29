"""Extract materials (keyframes + audio) from user-uploaded video."""

import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path

import cv2
import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

STORAGE_ROOT = Path("storage")
UPLOADS_DIR = STORAGE_ROOT / "uploads"
FRAMES_DIR = STORAGE_ROOT / "frames"

FRAME_COUNT_PER_SEGMENT = 1  # extract 1 keyframe per segment


def cartoonize_image(image_path: str, output_path: str | None = None) -> str:
    """Apply cartoon effect to an image using bilateral filter + edge detection + color quantization.

    Returns the output path (overwrites original if output_path is None).
    """
    img = cv2.imread(image_path)
    if img is None:
        logger.warning("Cannot read image for cartoonization: %s", image_path)
        return image_path

    # Downscale for faster processing, then upscale back
    h, w = img.shape[:2]
    scale = 1.0
    if max(h, w) > 1280:
        scale = 1280 / max(h, w)
        small = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    else:
        small = img

    # 1. Smooth colors while preserving edges (bilateral filter)
    smooth = cv2.bilateralFilter(small, d=9, sigmaColor=75, sigmaSpace=75)
    smooth = cv2.bilateralFilter(smooth, d=9, sigmaColor=75, sigmaSpace=75)

    # 2. Color quantization — reduce to fewer color levels for a flat cartoon look
    quantized = smooth.copy()
    div = 24  # color levels
    quantized = (quantized // div) * div + div // 2

    # 3. Edge detection for cartoon outlines
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 5)
    edges = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, blockSize=9, C=7
    )

    # 4. Combine edges with quantized colors
    edges_colored = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
    cartoon = cv2.bitwise_and(quantized, edges_colored)

    # 5. Slightly boost saturation for a more vibrant cartoon look
    cartoon_hsv = cv2.cvtColor(cartoon, cv2.COLOR_BGR2HSV).astype(np.float32)
    cartoon_hsv[:, :, 1] = np.clip(cartoon_hsv[:, :, 1] * 1.2, 0, 255)
    cartoon = cv2.cvtColor(cartoon_hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    # Upscale back if we downscaled
    if scale < 1.0:
        cartoon = cv2.resize(cartoon, (w, h), interpolation=cv2.INTER_LANCZOS4)

    out = output_path or image_path
    cv2.imwrite(out, cartoon)
    return out


def _ensure_dirs() -> None:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)


async def save_upload_video(note_id: int, file_bytes: bytes, filename: str) -> str:
    """Save uploaded video to storage and return the local path."""
    _ensure_dirs()
    ext = Path(filename).suffix or ".mp4"
    out_path = UPLOADS_DIR / f"note_{note_id}_source{ext}"
    out_path.write_bytes(file_bytes)
    return str(out_path)


async def extract_keyframes(
    video_path: str,
    num_segments: int,
) -> list[str]:
    """Extract evenly-spaced keyframes from a video file.

    Returns list of image file paths, one per segment.
    """
    _ensure_dirs()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.warning("FFmpeg not found, cannot extract keyframes")
        return []

    # Get video duration
    duration = await _probe_duration(video_path)
    if duration <= 0:
        return []

    frame_paths: list[str] = []
    for i in range(num_segments):
        timestamp = duration * (i + 0.5) / num_segments
        out_path = FRAMES_DIR / f"frame_{i:03d}.png"
        cmd = [
            ffmpeg, "-y",
            "-ss", str(timestamp),
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "2",
            str(out_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0 and out_path.exists():
            frame_paths.append(str(out_path))
        else:
            logger.warning("Failed to extract frame at %s: %s", timestamp, stderr.decode(errors="replace")[:200])

    return frame_paths


async def extract_audio(video_path: str) -> str | None:
    """Extract audio track from video. Returns audio file path or None."""
    _ensure_dirs()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None

    out_path = UPLOADS_DIR / f"audio_{Path(video_path).stem}.mp3"
    cmd = [
        ffmpeg, "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "libmp3lame",
        "-q:a", "4",
        str(out_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode == 0 and out_path.exists():
        return str(out_path)
    logger.warning("Failed to extract audio: %s", stderr.decode(errors="replace")[:200])
    return None


async def _probe_duration(path: str) -> float:
    """Return duration of a media file in seconds."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    cmd = [
        ffprobe, "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    try:
        return float(stdout.decode().strip())
    except (ValueError, UnicodeDecodeError):
        return 0.0


async def generate_materials_from_video(
    video_path: str,
    script: dict,
) -> list[dict]:
    """Generate materials from an uploaded video based on script segments.

    Returns list of material dicts (keyframes as images, audio).
    """
    segments = script.get("segments", [])
    num_segments = len(segments) or 1

    materials: list[dict] = []

    # Extract keyframes
    frame_paths = await extract_keyframes(video_path, num_segments)
    for i, (seg, frame_path) in enumerate(zip(segments, frame_paths)):
        seg_id = int(seg.get("id", i + 1))
        # Apply cartoon effect in a thread to avoid blocking the event loop
        cartoon_path = await asyncio.to_thread(cartoonize_image, frame_path)
        materials.append({
            "type": "image",
            "url": None,
            "local_path": cartoon_path,
            "prompt": f"Cartoon-style keyframe from source video at segment {seg_id}",
            "metadata": {"segment_id": seg_id, "kind": "video_frame_cartoon"},
        })

    # If fewer frames than segments, generate text cards for the rest
    if len(frame_paths) < len(segments):
        from app.services.material_gen import _generate_text_card
        for i in range(len(frame_paths), len(segments)):
            seg = segments[i]
            card = await _generate_text_card(seg)
            if card:
                materials.append(card)

    # If no frames extracted at all, fall back to text cards for all segments
    if not frame_paths:
        from app.services.material_gen import _generate_text_card
        for seg in segments:
            card = await _generate_text_card(seg)
            if card:
                materials.append(card)

    # Extract audio
    audio_path = await extract_audio(video_path)
    if audio_path:
        materials.append({
            "type": "audio",
            "url": None,
            "local_path": audio_path,
            "prompt": "Background audio from source video",
            "metadata": {"kind": "source_audio"},
        })

    # Add matched music from catalog
    from app.services.material_gen import _match_music
    music_mood = script.get("music_mood", "neutral")
    music = _match_music(music_mood)
    materials.extend(music)

    return materials
