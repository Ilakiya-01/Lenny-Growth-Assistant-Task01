"""Parsing of structured (JSON) model output.

Several agent components ask the configured provider for a small JSON object:
the optional intent classifier and the artifact skill. Models routinely wrap that
JSON in prose or a fenced code block, so extraction is shared here instead of
being reimplemented per component. Nothing in this module interprets model
reasoning - it only locates and parses the JSON object.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger("lenny.agent.structured")


def extract_json_object(raw: str) -> dict[str, object] | None:
    """Return the first JSON object in ``raw``, tolerating fenced code blocks."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        logger.debug("Structured output was not valid JSON")
        return None
    return payload if isinstance(payload, dict) else None


__all__ = ["extract_json_object"]
