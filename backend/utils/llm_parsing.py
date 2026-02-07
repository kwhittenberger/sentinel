"""Utilities for parsing JSON from LLM responses."""

import json


def parse_llm_json(text: str) -> dict:
    """
    Parse JSON from an LLM response, stripping markdown code fences if present.

    Handles these common LLM response formats:
      - Raw JSON
      - JSON wrapped in ```json ... ```
      - JSON wrapped in ``` ... ```

    Args:
        text: Raw LLM response text

    Returns:
        Parsed dictionary

    Raises:
        json.JSONDecodeError: If the extracted text is not valid JSON
    """
    stripped = text.strip()

    if "```json" in stripped:
        json_start = stripped.find("```json") + 7
        json_end = stripped.find("```", json_start)
        stripped = stripped[json_start:json_end].strip()
    elif "```" in stripped:
        json_start = stripped.find("```") + 3
        json_end = stripped.find("```", json_start)
        stripped = stripped[json_start:json_end].strip()

    return json.loads(stripped)
