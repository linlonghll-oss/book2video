import json
import logging

import httpx
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
你是一位专业的中文文案编辑，擅长优化文字的表述方式，使文案更精炼、生动、有感染力。

核心原则：
- 修正错别字、用词不当、语病、标点错误
- 优化措辞和句式：将平淡冗长的表述改为简洁有力的表达，将模糊的词语替换为更精准生动的用词
- 增强文字的节奏感和画面感，适当使用排比、短句等修辞手法
- 标题如果可以更吸引人，在不偏离原意的前提下优化
- 保持原文核心含义和事实不变，不添加原文没有的信息
- 保持原文的整体语气和风格

输出格式要求：
返回纯 JSON，不要包含 markdown 代码块标记，结构如下：
{
  "title": "优化后的标题",
  "body": "优化后的正文"
}
"""

DEFAULT_TEMPERATURE = 0.5


def _dry_run_response(title: str, body: str) -> dict:
    return {"status": "done", "title": title, "body": body}


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


async def refine_text(
    title: str,
    body: str,
    model_config: dict | None = None,
) -> dict:
    cfg = model_config or {}
    api_key = cfg.get("api_key") or settings.LLM_API_KEY
    base_url = cfg.get("base_url") or settings.LLM_BASE_URL
    model_id = cfg.get("model_id") or settings.LLM_MODEL
    temperature = float(cfg.get("temperature", DEFAULT_TEMPERATURE))

    if not api_key:
        logger.info("No LLM API key configured, returning dry-run response for refine")
        return _dry_run_response(title, body)

    user_prompt = f"""请修正以下笔记文案中的错别字和措辞问题。

标题：{title}

正文：
---
{body}
---

请输出符合格式要求的 JSON。"""

    try:
        http_client = httpx.AsyncClient(verify=False) if "coze" in str(base_url) else None
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, http_client=http_client)
        try:
            response = await client.chat.completions.create(
                model=model_id,
                max_tokens=4096,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            text = response.choices[0].message.content or ""
            if not text.strip():
                return {"status": "error", "message": "LLM returned empty response"}
        finally:
            if http_client:
                await http_client.aclose()
    except Exception as exc:
        logger.exception("LLM API call failed for refine")
        return {"status": "error", "message": f"LLM API call failed: {exc}"}

    parsed = _parse_json_response(text)
    if parsed is None:
        return {"status": "error", "message": "Failed to parse LLM response as JSON"}

    refined_title = parsed.get("title", title)
    refined_body = parsed.get("body", body)
    return {"status": "done", "title": refined_title, "body": refined_body}
