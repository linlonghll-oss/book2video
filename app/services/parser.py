import re
from typing import Optional


def parse_markdown(text: str) -> dict:
    if not text:
        return {"title": "", "sections": []}

    lines = text.split("\n")
    title = ""
    sections = []
    current_section = None
    code_fence = None
    code_lines = []

    for line in lines:
        if code_fence is not None:
            if line.rstrip() == code_fence:
                if current_section is not None:
                    current_section["content"] += "\n" + "\n".join(code_lines)
                code_fence = None
                code_lines = []
            else:
                code_lines.append(line)
            continue

        fence_match = re.match(r'^(`{3,}|~{3,})', line)
        if fence_match:
            code_fence = fence_match.group(1)
            code_lines = []
            continue

        heading_match = re.match(r'^(#{1,6})\s+(.*)', line)
        if heading_match:
            level = len(heading_match.group(1))
            content = heading_match.group(2).strip()

            if level == 1 and not title:
                title = content
                current_section = None
                continue

            if current_section is not None:
                sections.append(current_section)

            current_section = {"type": "heading", "level": level, "content": content}
            continue

        if current_section is not None:
            stripped = line.strip()
            if stripped.startswith("- ") or stripped.startswith("* ") or stripped.startswith("+ "):
                item_text = re.sub(r'^[-*+]\s+', '', stripped)
                if current_section["type"] != "list":
                    sections.append(current_section)
                    current_section = {"type": "list", "level": current_section["level"], "content": item_text}
                else:
                    current_section["content"] += "\n" + item_text
                continue

            ordered_match = re.match(r'^(\d+)\.\s+(.*)', stripped)
            if ordered_match:
                item_text = ordered_match.group(2)
                if current_section["type"] != "ordered_list":
                    sections.append(current_section)
                    current_section = {"type": "ordered_list", "level": current_section["level"], "content": item_text}
                else:
                    current_section["content"] += "\n" + item_text
                continue

            if stripped == "":
                if current_section["type"] in ("paragraph",):
                    sections.append(current_section)
                    current_section = None
                continue

            if current_section["type"] in ("heading",):
                sections.append(current_section)
                current_section = {"type": "paragraph", "level": current_section["level"], "content": stripped}
            else:
                current_section["content"] += "\n" + stripped
            continue

        stripped = line.strip()
        if stripped:
            current_section = {"type": "paragraph", "level": 0, "content": stripped}

    if current_section is not None:
        sections.append(current_section)

    return {"title": title, "sections": sections}
