"""Shared Ollama client: availability check, generation call, tolerant JSON parsing.

Single home for logic previously duplicated across alias_resolution.py,
relationship_extraction.py, and verify_entity_types.py (STU-446).
"""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request

DEFAULT_URL = "http://localhost:11434"
DEFAULT_TIMEOUT = 30


def is_available(url: str = DEFAULT_URL, timeout: int = 2) -> bool:
    """Return True if Ollama is reachable at url/api/tags."""
    try:
        req = urllib.request.Request(f"{url}/api/tags", method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except (urllib.error.URLError, socket.timeout, OSError):
        return False


def generate(
    prompt: str,
    *,
    model: str,
    url: str = DEFAULT_URL,
    timeout: int = DEFAULT_TIMEOUT,
    temperature: float = 0.0,
    num_predict: int | None = None,
) -> str | None:
    """Call Ollama's /api/generate. Returns the raw response text, or None on failure."""
    options: dict = {"temperature": temperature}
    if num_predict is not None:
        options["num_predict"] = num_predict
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": options,
    }).encode()
    req = urllib.request.Request(
        f"{url}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, socket.timeout, OSError, json.JSONDecodeError):
        return None
    return data.get("response", "")


def parse_json_response(text: str) -> dict | None:
    """Tolerantly parse an LLM response as JSON: json.loads, then first {...} block, else None."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[^{}]+\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def generate_json(
    prompt: str,
    *,
    model: str,
    url: str = DEFAULT_URL,
    timeout: int = DEFAULT_TIMEOUT,
    temperature: float = 0.0,
    num_predict: int | None = None,
) -> dict | None:
    """Call generate() and tolerantly parse the response as JSON. None on any failure."""
    raw = generate(
        prompt,
        model=model,
        url=url,
        timeout=timeout,
        temperature=temperature,
        num_predict=num_predict,
    )
    if raw is None:
        return None
    return parse_json_response(raw)
