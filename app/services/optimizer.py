import json
import logging

import httpx
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

STYLE_PROMPTS = {
    "knowledge": (
        "知识解读风格：以清晰、逻辑严密的方式讲解知识点，"
        "适合科普和教育类视频。语气专业但不生硬，"
        "用通俗易懂的语言解释概念，适当使用类比帮助理解。"
    ),
    "story": (
        "故事讲述风格：用叙事手法呈现内容，"
        "适合引人入胜的视频。设置悬念和转折，"
        "用场景描写和情感铺垫增强代入感，"
        "像讲故事一样将知识点融入情节之中。"
    ),
    "checklist": (
        "清单体风格：以条目化、结构化的方式呈现内容，"
        "适合实用指南和操作类视频。每条简洁有力，"
        "配有明确的行动指引，方便观众逐条对照执行。"
    ),
}

DEFAULT_TEMPERATURE = 0.5
DEFAULT_MAX_TOKENS = 4096

SYSTEM_PROMPT = """\
你是一位专业的视频脚本策划师，擅长将书籍笔记改写为适合视频旁白的脚本，同时为每段旁白生成高质量的 AI 绘图提示词。

核心原则：
- 严格基于原文内容改写，不要添加原文中没有的事实、数据或观点
- 改写后的文案要适合口语化朗读，避免书面化长句
- 每个段落的旁白文案控制在 50-120 字之间，适合 3-8 秒的朗读时长
- 为每个段落提供画面建议(visual_hint)，中文描述，帮助理解画面意图
- image_prompt 为英文 AI 绘图提示词，直接可用于 Stable Diffusion / FLUX 模型生图
- 为每个段落标注情感基调(emotion)：neutral / positive / inspiring
- duration_hint 为建议朗读时长（秒），根据文案字数估算（约 15-20 字/秒）

image_prompt 写作要求（重要！）：
- 必须为英文，适合直接输入 AI 画图模型
- 包含具体的视觉元素：构图（composition）、光影（lighting）、色彩（color palette）、景别（shot type）
- 避免抽象描述，要有具体的物体、场景、动作
- 不要包含任何文字、字母、水印的描述
- 默认 16:9 横屏构图
- 字数控制在 20-50 个英文单词
- 格式示例："a solitary figure reading under a warm lamp in a cozy library, soft golden lighting, shallow depth of field, warm brown and amber tones, cinematic composition, 16:9"

输出格式要求：
返回纯 JSON，不要包含 markdown 代码块标记，结构如下：
{
  "title": "视频标题（简洁有力，10字以内）",
  "segments": [
    {
      "id": 1,
      "text": "旁白文案",
      "duration_hint": 5,
      "emotion": "neutral",
      "visual_hint": "画面建议（中文）",
      "image_prompt": "英文 AI 绘图提示词"
    }
  ],
  "total_duration_hint": 60,
  "style": "knowledge",
  "music_mood": "inspiring"
}

music_mood 取值范围：calm / positive / inspiring / energetic / reflective
total_duration_hint 为所有 segments 的 duration_hint 之和
"""


def _build_user_prompt(parsed_note: dict, style: str) -> str:
    style_instruction = STYLE_PROMPTS.get(style, STYLE_PROMPTS["knowledge"])

    title = parsed_note.get("title", "")
    sections = parsed_note.get("sections", [])

    note_parts = []
    if title:
        note_parts.append(f"# {title}")
    for section in sections:
        sec_type = section.get("type", "paragraph")
        level = section.get("level", 0)
        content = section.get("content", "")
        if sec_type == "heading":
            prefix = "#" * level if level else "#"
            note_parts.append(f"{prefix} {content}")
        elif sec_type in ("list", "ordered_list"):
            for line in content.split("\n"):
                note_parts.append(f"- {line}")
        else:
            note_parts.append(content)

    note_text = "\n".join(note_parts)
    if not note_text.strip():
        note_text = "(无有效内容)"

    return f"""请根据以下书籍笔记内容，改写为视频旁白脚本。

风格要求：{style_instruction}

原始笔记内容：
---
{note_text}
---

请输出符合格式要求的 JSON 脚本。"""


def _dry_run_response(parsed_note: dict, style: str) -> dict:
    title = parsed_note.get("title", "未命名笔记")
    sections = parsed_note.get("sections", [])
    segments = []
    for i, section in enumerate(sections, start=1):
        content = section.get("content", "")
        text = content[:100] if content else "（空内容）"
        segments.append({
            "id": i, "text": text, "duration_hint": 5,
            "emotion": "neutral", "visual_hint": "（dry-run，需 API Key 生成）", "image_prompt": "",
        })
    if not segments:
        segments.append({
            "id": 1, "text": title, "duration_hint": 5,
            "emotion": "neutral", "visual_hint": "（dry-run，需 API Key 生成）", "image_prompt": "",
        })
    total = sum(s["duration_hint"] for s in segments)
    return {
        "status": "done", "title": title[:10] if title else "视频标题",
        "segments": segments, "total_duration_hint": total,
        "style": style, "music_mood": "calm",
    }


def _parse_json_response(text: str) -> dict | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].rstrip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


def _validate_script(script: dict, style: str) -> dict:
    if not isinstance(script, dict):
        script = {}
    title = script.get("title", "")
    if not isinstance(title, str) or not title.strip():
        title = "视频标题"
    raw_segments = script.get("segments", [])
    if not isinstance(raw_segments, list):
        raw_segments = []
    segments = []
    for i, seg in enumerate(raw_segments, start=1):
        if not isinstance(seg, dict):
            continue
        image_prompt = str(seg.get("image_prompt", "")).strip()
        segments.append({
            "id": seg.get("id", i),
            "text": str(seg.get("text", "")),
            "duration_hint": max(1, int(seg.get("duration_hint", 5))),
            "emotion": seg.get("emotion", "neutral") if seg.get("emotion") in ("neutral", "positive", "inspiring") else "neutral",
            "visual_hint": str(seg.get("visual_hint", "")),
            "image_prompt": image_prompt if image_prompt else "",
        })
    if not segments:
        segments = [{"id": 1, "text": "（内容生成失败）", "duration_hint": 3, "emotion": "neutral", "visual_hint": "", "image_prompt": ""}]
    total = script.get("total_duration_hint")
    if not isinstance(total, (int, float)) or total <= 0:
        total = sum(s["duration_hint"] for s in segments)
    music_mood = script.get("music_mood", "calm")
    if music_mood not in ("calm", "positive", "inspiring", "energetic", "reflective"):
        music_mood = "calm"
    return {
        "status": "done", "title": title, "segments": segments,
        "total_duration_hint": int(total), "style": style, "music_mood": music_mood,
    }


async def optimize_script(
    parsed_note: dict,
    style: str | None = None,
    model_config: dict | None = None,
) -> dict:
    valid_styles = {"knowledge", "story", "checklist"}
    if style not in valid_styles:
        style = "knowledge"

    cfg = model_config or {}
    api_key = cfg.get("api_key") or settings.LLM_API_KEY
    base_url = cfg.get("base_url") or settings.LLM_BASE_URL
    model_id = cfg.get("model_id") or settings.LLM_MODEL
    temperature = float(cfg.get("temperature", DEFAULT_TEMPERATURE))
    max_tokens = int(cfg.get("max_tokens", DEFAULT_MAX_TOKENS))

    # Legacy mapping: if ANTHROPIC_API_KEY is set but LLM_API_KEY isn't
    if not api_key and settings.ANTHROPIC_API_KEY:
        logger.info("No LLM_API_KEY, returning dry-run response")
        return _dry_run_response(parsed_note, style)

    if not api_key:
        logger.info("No LLM API key configured, returning dry-run response")
        return _dry_run_response(parsed_note, style)

    user_prompt = _build_user_prompt(parsed_note, style)

    try:
        http_client = httpx.AsyncClient(verify=False) if "coze" in str(base_url) else None
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, http_client=http_client)
        try:
            response = await client.chat.completions.create(
                model=model_id,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            text = response.choices[0].message.content or ""
            if not text.strip():
                return {"status": "error", "script": None, "message": "LLM returned empty response"}
        finally:
            if http_client:
                await http_client.aclose()
    except Exception as exc:
        logger.exception("LLM API call failed")
        return {"status": "error", "script": None, "message": f"LLM API call failed: {exc}"}

    parsed = _parse_json_response(text)
    if parsed is None:
        return {
            "status": "error", "script": None,
            "message": "Failed to parse LLM response as JSON",
            "raw_response": text[:2000],
        }
    return _validate_script(parsed, style)
