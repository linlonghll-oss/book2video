"""FFmpeg-based video composition service.

Converts image + audio materials into a final H.264 MP4 video with
Ken Burns zoom, fade transitions, and optional background audio.
"""

import asyncio
import logging
import os
import shutil
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_RESOLUTION = "1920x1080"
DEFAULT_DURATION = 5.0  # seconds per image when no hint is given
FADE_DURATION = 1.0  # seconds for fade-in / fade-out between segments
KEN_BURNS_ZOOM = 1.08  # subtle zoom from 1.0x to this value

RESOLUTION_MAP = {
    "1920x1080": {"w": 1920, "h": 1080},
    "1080x1920": {"w": 1080, "h": 1920},
}


# ---------------------------------------------------------------------------
# TTS via edge-tts
# ---------------------------------------------------------------------------

async def _generate_tts_audio(text: str, output_path: str, voice: str | None = None) -> str | None:
    """Generate TTS audio file via edge-tts. Returns output_path on success."""
    try:
        import edge_tts
        tts_voice = voice or settings.TTS_VOICE
        communicate = edge_tts.Communicate(text, tts_voice)
        await communicate.save(output_path)
        return output_path
    except Exception:
        logger.exception("edge-tts generation failed for text: %s", text[:50])
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_resolution(config: dict | None) -> str:
    """Return resolution string like '1920x1080' from config or default."""
    if config and "resolution" in config:
        res = config["resolution"]
        if res in RESOLUTION_MAP:
            return res
    return DEFAULT_RESOLUTION


def _ensure_dir(path: str | Path) -> None:
    """Create directory (and parents) if it does not exist."""
    Path(path).mkdir(parents=True, exist_ok=True)


def _segment_duration(script: dict, segment_id: int) -> float:
    """Look up duration_hint for a segment; fall back to DEFAULT_DURATION."""
    for seg in script.get("segments", []):
        if seg.get("id") == segment_id:
            hint = seg.get("duration_hint")
            if hint and hint > 0:
                return float(hint)
    return DEFAULT_DURATION


def _get_metadata(m: dict) -> dict:
    """Return the metadata dict from a material, handling both 'meta_data' and 'metadata' keys."""
    return m.get("meta_data") or m.get("metadata") or {}


def _image_materials_for_segment(materials: list, segment_id: int) -> list[dict]:
    """Return image materials belonging to a given segment, ordered by kind."""
    imgs = [
        m for m in materials
        if m.get("type") == "image"
        and _get_metadata(m).get("segment_id") == segment_id
    ]
    # Prefer ai_generated over text_card when both exist
    kind_order = {"ai_generated": 0, "text_card": 1, "video_frame_cartoon": 2, "video_frame": 3}
    imgs.sort(key=lambda m: kind_order.get(_get_metadata(m).get("kind", ""), 99))
    return imgs


def _video_material_for_segment(materials: list, segment_id: int) -> dict | None:
    """Return the AI-generated video material for a segment (not segment_clip)."""
    for m in materials:
        if m.get("type") == "video" and _get_metadata(m).get("segment_id") == segment_id:
            if _get_metadata(m).get("kind") == "segment_clip":
                continue  # handled by _segment_clip_for_segment
            return m
    return None


def _segment_clip_for_segment(materials: list, segment_id: int) -> dict | None:
    """Return a segment_clip video (with audio+subtitle already baked in)."""
    for m in materials:
        if m.get("type") == "video" and _get_metadata(m).get("segment_id") == segment_id and _get_metadata(m).get("kind") == "segment_clip":
            return m
    return None


def _audio_materials(materials: list) -> list[dict]:
    """Return all audio materials."""
    return [m for m in materials if m.get("type") == "audio"]


def _audio_for_segment(materials: list, segment_id: int) -> dict | None:
    """Return an audio material for a specific segment."""
    for m in materials:
        if m.get("type") == "audio" and _get_metadata(m).get("segment_id") == segment_id:
            return m
    return None


def _ordered_segment_ids(script: dict, materials: list) -> list[int]:
    """Return segment ids that have image or video material, in script order."""
    ids = []
    for seg in script.get("segments", []):
        sid = seg.get("id")
        if sid is not None and (_image_materials_for_segment(materials, sid) or _video_material_for_segment(materials, sid)):
            ids.append(sid)
    return ids


# ---------------------------------------------------------------------------
# FFmpeg availability check
# ---------------------------------------------------------------------------

async def _check_ffmpeg() -> str | None:
    """Return the FFmpeg binary path, or None if unavailable."""
    path = shutil.which("ffmpeg")
    return path


# ---------------------------------------------------------------------------
# Build per-segment clip with Ken Burns zoom + fade
# ---------------------------------------------------------------------------

async def _render_segment_clip(
    ffmpeg: str,
    image_path: str,
    duration: float,
    resolution: str,
    output_path: str,
) -> None:
    """Render a single image into a short video clip with Ken Burns zoom.

    The zoom goes from 1.0x to KEN_BURNS_ZOOM over the clip duration,
    centred on the middle of the frame.
    """
    w = RESOLUTION_MAP[resolution]["w"]
    h = RESOLUTION_MAP[resolution]["h"]

    # Ken Burns: zoom from scale=1.0 to scale=KEN_BURNS_ZOOM, centred.
    # We use zoompan which produces a stream at a given framerate, then
    # encode to the desired duration.
    fps = 30
    total_frames = max(int(duration * fps), 2)
    zoom_start = 1.0
    zoom_end = KEN_BURNS_ZOOM

    # zoompan formula: zoom at frame n = zoom_start + (zoom_end - zoom_start) * n / (total_frames - 1)
    # zoompan expression: '1+(ZOOM_END-1)*on/(NF-1)' where NF = total_frames
    zoom_expr = f"{zoom_start}+({zoom_end}-{zoom_start})*on/({total_frames}-1)"

    vf = (
        f"zoompan=z='{zoom_expr}':d={total_frames}:s={w}x{h}:fps={fps},"
        f"fade=t=in:st=0:d={FADE_DURATION},"
        f"fade=t=out:st={duration - FADE_DURATION}:d={FADE_DURATION}"
    )

    cmd = [
        ffmpeg, "-y",
        "-loop", "1",
        "-i", image_path,
        "-vf", vf,
        "-t", str(duration),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        output_path,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"FFmpeg segment render failed (rc={proc.returncode}): "
            f"{stderr.decode(errors='replace')}"
        )


# ---------------------------------------------------------------------------
# Concatenate segment clips using concat demuxer
# ---------------------------------------------------------------------------

async def _concat_clips(
    ffmpeg: str,
    clip_paths: list[str],
    output_path: str,
) -> None:
    """Concatenate video clips via FFmpeg concat demuxer (re-encode)."""
    # Write a temporary concat list file
    concat_file = output_path + ".concat.txt"
    try:
        with open(concat_file, "w") as f:
            for p in clip_paths:
                # concat demuxer requires escaped paths; single quotes around
                # paths with spaces. We use relative-safe absolute paths.
                escaped = p.replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")

        cmd = [
            ffmpeg, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            output_path,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"FFmpeg concat failed (rc={proc.returncode}): "
                f"{stderr.decode(errors='replace')}"
            )
    finally:
        if os.path.exists(concat_file):
            os.unlink(concat_file)


# ---------------------------------------------------------------------------
# Mix background audio into video
# ---------------------------------------------------------------------------

async def _mix_audio(
    ffmpeg: str,
    video_path: str,
    audio_paths: list[str],
    output_path: str,
) -> None:
    """Mix one or more background audio tracks into the video.

    Multiple audio files are first mixed together, then combined with the
    video stream.  The result is trimmed to the shorter of video/audio.
    """
    if len(audio_paths) == 1:
        # Simple case: one audio file
        cmd = [
            ffmpeg, "-y",
            "-i", video_path,
            "-i", audio_paths[0],
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            output_path,
        ]
    else:
        # Multiple audio files: mix them first via amix, then mux with video
        # Build input args: -i video -i audio1 -i audio2 ...
        inputs = ["-i", video_path]
        for ap in audio_paths:
            inputs += ["-i", ap]

        # amix filter: mix all audio inputs (indices 1,2,...)
        n_audio = len(audio_paths)
        amix_inputs = "".join(f"[{i}:a]" for i in range(1, n_audio + 1))
        filter_complex = f"{amix_inputs}amix=inputs={n_audio}[a]"

        cmd = [
            ffmpeg, "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            output_path,
        ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"FFmpeg audio mix failed (rc={proc.returncode}): "
            f"{stderr.decode(errors='replace')}"
        )


# ---------------------------------------------------------------------------
# Font path for drawtext filter
# ---------------------------------------------------------------------------

_CJK_FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
]


def _find_cjk_font() -> str | None:
    """Return path to a CJK-capable font for FFmpeg drawtext."""
    for p in _CJK_FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


# ---------------------------------------------------------------------------
# Render subtitle bar as semi-transparent PNG via Pillow
# ---------------------------------------------------------------------------

_SUB_FONT_SIZE = 44
_SUB_MAX_CHARS_PER_LINE = 30
_SUB_MAX_LINES = 1
_SUB_LINE_SPACING = 12
_SUB_BAR_PADDING = 20
_SUB_BAR_Y_OFFSET = 60  # pixels from bottom


def _load_subtitle_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a CJK-capable font at the given size."""
    for p in _CJK_FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


_PUNCTS = set("，。、；：！？,…？！；：、—""''）】》")


def _split_text_to_phases(text: str, max_chars_per_line: int, max_lines: int) -> list[str]:
    """Split text into subtitle phases by punctuation, each within max_chars_per_line.

    Strategy: scan character by character, greedily accumulate until exceeding
    the limit, then backtrack to the last punctuation to break. Falls back to
    hard break only when there's no punctuation in the current segment.
    """
    if not text:
        return []

    lines: list[str] = []
    i = 0
    n = len(text)

    while i < n:
        # Try to take up to max_chars_per_line chars
        end = min(i + max_chars_per_line, n)
        segment = text[i:end]

        if len(segment) <= max_chars_per_line and end == n:
            # Last segment, take it all
            lines.append(segment)
            break

        # Look for the last punctuation mark within the segment
        last_punct = -1
        for j in range(len(segment) - 1, 0, -1):
            if segment[j] in _PUNCTS:
                last_punct = j
                break

        if last_punct >= 1:
            # Break after the punctuation
            lines.append(segment[:last_punct + 1])
            i += last_punct + 1
        else:
            # No punctuation found — hard break at limit
            lines.append(segment)
            i = end

    # Group lines into phases of max_lines each
    phases: list[str] = []
    for k in range(0, len(lines), max_lines):
        chunk = lines[k:k + max_lines]
        phases.append("\n".join(chunk))
    return phases


def _render_subtitle_png(lines_text: str, video_w: int, video_h: int, font_path: str | None, out_path: str) -> None:
    """Render a subtitle bar as a semi-transparent PNG for overlay."""
    if not lines_text or not lines_text.strip():
        return

    font = _load_subtitle_font(_SUB_FONT_SIZE) if not font_path else (
        ImageFont.truetype(font_path, _SUB_FONT_SIZE) if os.path.exists(font_path) else _load_subtitle_font(_SUB_FONT_SIZE)
    )

    lines = lines_text.split("\n")

    # Measure text dimensions
    dummy_img = Image.new("RGBA", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)
    line_heights = []
    total_text_h = 0
    for line in lines:
        bbox = dummy_draw.textbbox((0, 0), line, font=font)
        lh = bbox[3] - bbox[1] + _SUB_LINE_SPACING
        line_heights.append(lh)
        total_text_h += lh
    total_text_h -= _SUB_LINE_SPACING

    bar_h = total_text_h + 2 * _SUB_BAR_PADDING
    bar_y = video_h - bar_h - _SUB_BAR_Y_OFFSET

    img = Image.new("RGBA", (video_w, video_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    y = bar_y + (bar_h - total_text_h) // 2
    for i, line in enumerate(lines):
        bbox = dummy_draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        x = (video_w - line_w) // 2
        draw.text((x, y), line, fill=(255, 255, 255, 255), font=font)
        y += line_heights[i]

    img.save(out_path, "PNG")


# ---------------------------------------------------------------------------
# Generate per-segment video clips (image + TTS + subtitle via FFmpeg)
# ---------------------------------------------------------------------------

async def generate_subtitles(
    note_id: int,
    script: dict,
) -> list[dict]:
    """Generate subtitle PNG materials for each segment.

    Returns a list of dicts with keys: segment_id, local_path, phases, text.
    Each entry may have multiple phase PNGs stored in meta_data.
    """
    font_path = _find_cjk_font()
    output_dir = os.path.join("storage", "subtitles")
    _ensure_dir(output_dir)

    segments = script.get("segments", [])
    if not segments:
        return []

    results: list[dict] = []
    for seg in segments:
        seg_id = seg.get("id", 0)
        seg_text = seg.get("text", "")

        if not seg_text or not seg_text.strip():
            continue

        phases = _split_text_to_phases(seg_text, _SUB_MAX_CHARS_PER_LINE, _SUB_MAX_LINES)
        if not phases:
            continue

        phase_paths: list[str] = []
        for pi, phase_text in enumerate(phases):
            png_path = os.path.join(output_dir, f"note_{note_id}_seg_{seg_id}_phase_{pi}.png")
            await asyncio.to_thread(_render_subtitle_png, phase_text, 1920, 1080, font_path, png_path)
            if os.path.isfile(png_path):
                phase_paths.append(png_path)

        if phase_paths:
            results.append({
                "segment_id": seg_id,
                "text": seg_text,
                "phases": phases,
                "phase_paths": phase_paths,
            })

    return results


async def generate_segment_clips(
    note_id: int,
    materials: list[dict],
    script: dict,
    voice: str | None = None,
    subtitle_materials: list[dict] | None = None,
) -> list[dict]:
    """Generate per-segment video clips: image + TTS audio + subtitle overlay.

    If subtitle_materials is provided, uses pre-generated subtitle PNGs.
    Otherwise generates subtitles inline (legacy behavior).

    Returns a list of dicts with keys: segment_id, local_path, duration.
    """
    ffmpeg = await _check_ffmpeg()
    if not ffmpeg:
        return []

    ffprobe = shutil.which("ffprobe") or "ffprobe"
    font_path = _find_cjk_font()

    # Build subtitle lookup: segment_id → {phase_paths, phases}
    sub_lookup: dict[int, dict] = {}
    if subtitle_materials:
        for sm in subtitle_materials:
            sid = sm.get("segment_id", 0)
            sub_lookup[sid] = {
                "phase_paths": sm.get("phase_paths", []),
                "phases": sm.get("phases", []),
            }

    # Check if drawtext filter is available
    has_drawtext = False
    try:
        cmd = [ffmpeg, "-filters"]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if b"drawtext" in stdout:
            has_drawtext = True
    except Exception:
        pass

    output_dir = os.path.join("storage", "segment_videos")
    sub_dir = os.path.join(output_dir, "sub_tmp")
    _ensure_dir(sub_dir)
    _ensure_dir(output_dir)

    segments = script.get("segments", [])
    if not segments:
        return []

    clip_results: list[dict] = []
    tts_dir = os.path.join("storage", "segment_videos", "tts_tmp")

    for seg in segments:
        seg_id = seg.get("id", 0)
        seg_text = seg.get("text", "")

        # Find image material for this segment
        imgs = _image_materials_for_segment(materials, seg_id)
        if not imgs:
            logger.warning("No image for segment %s, skipping", seg_id)
            continue
        img = imgs[0]
        img_path = img.get("local_path", "")
        if not img_path or not os.path.isfile(img_path):
            logger.warning("Image file missing for segment %s: %s", seg_id, img_path)
            continue

        # Find or generate TTS audio for this segment
        tts_path = None
        existing_audio = _audio_for_segment(materials, seg_id)
        if existing_audio:
            ap = existing_audio.get("local_path", "")
            if ap and os.path.isfile(ap):
                tts_path = ap
        if not tts_path:
            _ensure_dir(tts_dir)
            tts_path = os.path.join(tts_dir, f"tts_{note_id}_{seg_id}.mp3")
            tts_result = await _generate_tts_audio(seg_text, tts_path, voice)
            if not tts_result or not os.path.isfile(tts_path):
                logger.warning("TTS failed for segment %s, generating clip without audio", seg_id)
                tts_path = None

        # Determine duration from TTS audio
        duration = DEFAULT_DURATION
        if tts_path:
            tts_duration = await _probe_duration(ffprobe, tts_path)
            if tts_duration > 0:
                duration = tts_duration + 0.5  # small padding

        # Build FFmpeg command: image → video with Ken Burns + audio
        clip_path = os.path.join(output_dir, f"note_{note_id}_seg_{seg_id}.mp4")

        # Ken Burns zoom expression
        fps = 30
        total_frames = max(int(duration * fps), 2)
        zoom_expr = f"1.0+({KEN_BURNS_ZOOM}-1.0)*on/({total_frames}-1)"

        # Stage 1: render base clip (zoompan + fade, with or without audio)
        base_path = clip_path + ".base.mp4"
        vf = (
            f"zoompan=z='{zoom_expr}':d={total_frames}:s=1920x1080:fps={fps},"
            f"fade=t=in:st=0:d={FADE_DURATION},"
            f"fade=t=out:st={duration - FADE_DURATION}:d={FADE_DURATION}"
        )

        if tts_path:
            cmd = [
                ffmpeg, "-y",
                "-loop", "1", "-i", img_path,
                "-i", tts_path,
                "-vf", vf,
                "-t", str(duration),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
                "-c:a", "aac",
                "-shortest",
                base_path,
            ]
        else:
            cmd = [
                ffmpeg, "-y",
                "-loop", "1", "-i", img_path,
                "-vf", vf,
                "-t", str(duration),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
                "-an",
                base_path,
            ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error(
                    "Base clip render failed for seg %s (rc=%d): %s",
                    seg_id, proc.returncode, stderr.decode(errors="replace")[:500],
                )
                continue
        except Exception:
            logger.exception("Failed to render base clip for segment %s", seg_id)
            continue

        # Stage 2: overlay subtitle PNGs
        # Resolve subtitle PNGs: prefer pre-generated from subtitle_materials, else generate inline
        sub_png_paths: list[str] = []
        phases: list[str] = []

        if seg_id in sub_lookup:
            sub_png_paths = sub_lookup[seg_id]["phase_paths"]
            phases = sub_lookup[seg_id]["phases"]
        elif seg_text and seg_text.strip():
            phases = _split_text_to_phases(seg_text, _SUB_MAX_CHARS_PER_LINE, _SUB_MAX_LINES)
            for pi, phase_text in enumerate(phases):
                png_path = os.path.join(sub_dir, f"sub_{note_id}_{seg_id}_{pi}.png")
                await asyncio.to_thread(_render_subtitle_png, phase_text, 1920, 1080, font_path, png_path)
                if os.path.isfile(png_path):
                    sub_png_paths.append(png_path)

        # Filter to existing files only
        sub_png_paths = [p for p in sub_png_paths if os.path.isfile(p)]

        if not sub_png_paths:
            shutil.move(base_path, clip_path)
        elif len(sub_png_paths) == 1:
            overlay_cmd = [
                ffmpeg, "-y",
                "-i", base_path,
                "-i", sub_png_paths[0],
                "-filter_complex", "[0:v][1:v]overlay=0:0",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "copy",
                clip_path,
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *overlay_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode != 0:
                    logger.warning("Subtitle overlay failed for seg %s: %s", seg_id, stderr.decode(errors="replace")[:300])
                    if os.path.isfile(clip_path): os.remove(clip_path)
                    shutil.move(base_path, clip_path)
                else:
                    os.remove(base_path)
            except Exception:
                logger.exception("Subtitle overlay error for segment %s", seg_id)
                if os.path.isfile(clip_path): os.remove(clip_path)
                shutil.move(base_path, clip_path)
        else:
            # Multi-phase subtitles — overlay each phase with timed enable
            phase_duration = duration / len(sub_png_paths)

            inputs = ["-i", base_path]
            for p in sub_png_paths:
                inputs += ["-i", p]

            filter_parts = []
            prev_label = "0:v"
            for pi in range(len(sub_png_paths)):
                in_label = f"{pi + 1}:v"
                out_label = f"v{pi}"
                t_start = pi * phase_duration
                t_end = (pi + 1) * phase_duration
                enable_expr = f"between(t,{t_start:.2f},{t_end:.2f})"
                filter_parts.append(
                    f"[{prev_label}][{in_label}]overlay=0:0:enable='{enable_expr}'[{out_label}]"
                )
                prev_label = out_label

            filter_complex = ";".join(filter_parts)

            overlay_cmd = [
                ffmpeg, "-y",
                *inputs,
                "-filter_complex", filter_complex,
                "-map", f"[{prev_label}]",
                "-map", "0:a?",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "copy",
                clip_path,
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *overlay_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode != 0:
                    logger.warning("Multi-phase subtitle overlay failed for seg %s: %s", seg_id, stderr.decode(errors="replace")[:300])
                    if os.path.isfile(clip_path): os.remove(clip_path)
                    shutil.move(base_path, clip_path)
                else:
                    os.remove(base_path)
            except Exception:
                logger.exception("Multi-phase subtitle overlay error for segment %s", seg_id)
                if os.path.isfile(clip_path): os.remove(clip_path)
                shutil.move(base_path, clip_path)

        # Verify final clip exists and measure duration
        if not os.path.isfile(clip_path):
            logger.warning("Final clip not found for segment %s", seg_id)
            continue

        clip_duration = await _probe_duration(ffprobe, clip_path)
        clip_results.append({
            "segment_id": seg_id,
            "local_path": clip_path,
            "duration": clip_duration or duration,
            "text": seg_text,
        })

    # Clean up temp directories
    if os.path.isdir(tts_dir):
        shutil.rmtree(tts_dir, ignore_errors=True)
    if os.path.isdir(sub_dir):
        shutil.rmtree(sub_dir, ignore_errors=True)

    return clip_results


# ---------------------------------------------------------------------------
# Probe video duration (ffprobe)
# ---------------------------------------------------------------------------

async def _probe_duration(ffprobe: str, path: str) -> float:
    """Return duration of a media file in seconds via ffprobe."""
    cmd = [
        ffprobe,
        "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return 0.0
    try:
        return float(stdout.decode().strip())
    except (ValueError, UnicodeDecodeError):
        return 0.0


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def compose_video(
    note_id: int,
    materials: list,
    script: dict,
    config: dict | None = None,
) -> dict:
    """Compose image + audio materials into a final H.264 MP4 video.

    Parameters
    ----------
    note_id : int
        Identifier for the note (used in output filename).
    materials : list[dict]
        List of material dicts with keys type, local_path, metadata.
    script : dict
        Script with segments defining timing and ordering.
    config : dict | None
        Optional config, e.g. {"resolution": "1080x1920"}.

    Returns
    -------
    dict
        Result with status, output_path, duration, resolution, file_size, message.
    """
    # --- Check FFmpeg availability ---
    ffmpeg = await _check_ffmpeg()
    if not ffmpeg:
        return {
            "status": "error",
            "output_path": None,
            "duration": 0.0,
            "resolution": None,
            "file_size": 0,
            "message": "FFmpeg is not installed or not found on PATH. Please install FFmpeg first.",
        }

    ffprobe = shutil.which("ffprobe")

    # --- Resolve settings ---
    resolution = _resolve_resolution(config)
    w = RESOLUTION_MAP[resolution]["w"]
    h = RESOLUTION_MAP[resolution]["h"]

    # --- Ensure output directory ---
    output_dir = os.path.join("storage", "videos")
    _ensure_dir(output_dir)

    # --- Determine segments with images ---
    segment_ids = _ordered_segment_ids(script, materials)
    if not segment_ids:
        return {
            "status": "error",
            "output_path": None,
            "duration": 0.0,
            "resolution": resolution,
            "file_size": 0,
            "message": "No image materials found for any segment; cannot compose video.",
        }

    # --- Collect background audio paths ---
    audio_materials = _audio_materials(materials)
    audio_paths = [
        m["local_path"] for m in audio_materials
        if m.get("local_path") and os.path.isfile(m["local_path"])
    ]

    # --- Render each segment clip in a temp directory ---
    tmp_dir = tempfile.mkdtemp(prefix="composer_")
    try:
        clip_paths: list[str] = []
        tts_paths: list[str | None] = []

        for idx, seg_id in enumerate(segment_ids):

            # Check if there's a segment_clip (already has audio + subtitle)
            seg_clip = _segment_clip_for_segment(materials, seg_id)
            if seg_clip:
                vid_path = seg_clip.get("local_path") or seg_clip.get("url")
                if vid_path and os.path.isfile(vid_path):
                    # Segment clip already has audio + subtitle — just re-encode resolution
                    clip_path = os.path.join(tmp_dir, f"segment_{seg_id:04d}.mp4")
                    cmd = [
                        ffmpeg, "-y",
                        "-i", vid_path,
                        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black",
                        "-c:v", "libx264",
                        "-pix_fmt", "yuv420p",
                        "-r", "30",
                        "-c:a", "aac",
                        clip_path,
                    ]
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await proc.communicate()
                    if proc.returncode == 0 and os.path.isfile(clip_path):
                        clip_paths.append(clip_path)
                        tts_paths.append(None)  # audio already in clip
                        continue
                    else:
                        logger.warning("Failed to re-encode segment clip for segment %s, falling back", seg_id)

            duration = _segment_duration(script, seg_id)

            # Generate TTS narration for this segment
            seg_text = None
            for seg in script.get("segments", []):
                if seg.get("id") == seg_id:
                    seg_text = seg.get("text", "")
                    break
            tts_path = None
            if seg_text and settings.TTS_ENGINE == "edge-tts":
                tts_path = await _generate_tts_audio(
                    seg_text,
                    os.path.join(tmp_dir, f"tts_{seg_id:04d}.mp3"),
                )
                if tts_path:
                    tts_duration = await _probe_duration(
                        shutil.which("ffprobe") or "ffprobe", tts_path
                    )
                    if tts_duration > 0:
                        duration = tts_duration + 0.5
            tts_paths.append(tts_path)

            # Check if there's an AI-generated video clip for this segment
            vid_material = _video_material_for_segment(materials, seg_id)
            if vid_material:
                vid_path = vid_material.get("local_path") or vid_material.get("url")
                if vid_path and os.path.isfile(vid_path):
                    # Use the AI-generated video directly — re-encode to target resolution
                    clip_path = os.path.join(tmp_dir, f"segment_{seg_id:04d}.mp4")
                    cmd = [
                        ffmpeg, "-y",
                        "-i", vid_path,
                        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black",
                        "-c:v", "libx264",
                        "-pix_fmt", "yuv420p",
                        "-r", "30",
                        "-an",  # strip audio; TTS will be mixed later
                        clip_path,
                    ]
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await proc.communicate()
                    if proc.returncode == 0 and os.path.isfile(clip_path):
                        clip_paths.append(clip_path)
                        continue
                    else:
                        logger.warning("Failed to re-encode AI video for segment %s, falling back to image", seg_id)

            # Fallback: render from image with Ken Burns
            imgs = _image_materials_for_segment(materials, seg_id)
            if not imgs:
                return {
                    "status": "error",
                    "output_path": None,
                    "duration": 0.0,
                    "resolution": resolution,
                    "file_size": 0,
                    "message": f"No image or video material found for segment {seg_id}",
                }
            img = imgs[0]
            img_path = img.get("local_path", "")

            if not img_path or not os.path.isfile(img_path):
                return {
                    "status": "error",
                    "output_path": None,
                    "duration": 0.0,
                    "resolution": resolution,
                    "file_size": 0,
                    "message": f"Image file not found for segment {seg_id}: {img_path}",
                }

            clip_path = os.path.join(tmp_dir, f"segment_{seg_id:04d}.mp4")
            await _render_segment_clip(ffmpeg, img_path, duration, resolution, clip_path)
            clip_paths.append(clip_path)

        # --- Mix TTS into segment clips if available ---
        if any(tts_paths):
            mixed_clip_paths: list[str] = []
            for i, (clip, tts) in enumerate(zip(clip_paths, tts_paths)):
                if tts and os.path.isfile(tts):
                    mixed_path = os.path.join(tmp_dir, f"mixed_{i:04d}.mp4")
                    cmd = [
                        ffmpeg, "-y",
                        "-i", clip,
                        "-i", tts,
                        "-c:v", "copy",
                        "-c:a", "aac",
                        "-shortest",
                        mixed_path,
                    ]
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await proc.communicate()
                    if proc.returncode == 0 and os.path.isfile(mixed_path):
                        mixed_clip_paths.append(mixed_path)
                    else:
                        mixed_clip_paths.append(clip)
                else:
                    mixed_clip_paths.append(clip)
            clip_paths = mixed_clip_paths

        # --- Concatenate all segment clips ---
        concat_output = os.path.join(tmp_dir, "concat_result.mp4")
        await _concat_clips(ffmpeg, clip_paths, concat_output)

        # --- Mix background audio if available (only when clips don't already have audio) ---
        # Skip if all clips are segment_clip type (they already include audio)
        has_segment_clips = any(
            _segment_clip_for_segment(materials, sid) is not None
            for sid in segment_ids
        )
        final_output = os.path.join(output_dir, f"note_{note_id}.mp4")
        if audio_paths and not has_segment_clips:
            audio_mix_output = os.path.join(tmp_dir, "with_audio.mp4")
            await _mix_audio(ffmpeg, concat_output, audio_paths, audio_mix_output)
            shutil.move(audio_mix_output, final_output)
        else:
            shutil.move(concat_output, final_output)

        # --- Gather result metadata ---
        duration = 0.0
        if ffprobe:
            duration = await _probe_duration(ffprobe, final_output)

        file_size = os.path.getsize(final_output) if os.path.isfile(final_output) else 0

        return {
            "status": "done",
            "output_path": final_output,
            "duration": duration,
            "resolution": resolution,
            "file_size": file_size,
            "message": "Video composed successfully",
        }

    except Exception as exc:
        return {
            "status": "error",
            "output_path": None,
            "duration": 0.0,
            "resolution": resolution,
            "file_size": 0,
            "message": f"Composition failed: {exc}",
        }

    finally:
        # Clean up temp directory
        shutil.rmtree(tmp_dir, ignore_errors=True)
