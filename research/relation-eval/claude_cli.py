"""One stateless JSON turn through the Claude Code CLI.

Why the CLI and not the anthropic SDK: this project's Studio config already runs
on `provider: claude-code`, so the CLI bills the subscription the rest of the
pipeline bills. research/ner-eval used the SDK directly and now needs API credit
its sibling does not.

What is lost is `output_config.format.json_schema`: `claude -p` has no schema
enforcement, so the model's JSON is asked for in the prompt and validated here by
the caller. Every caller must treat a well-formed response as unverified — a type
outside the enum arrives as a plain string, not an error.

Nothing here is a pipeline dependency; the CLI is a dev-machine tool.
"""
import json
import re
import subprocess

DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_TIMEOUT = 300

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class ClaudeError(RuntimeError):
    pass


def _unfence(text: str) -> str:
    match = _FENCE.match(text)
    return match.group(1) if match else text.strip()


def complete_json(
    prompt: str,
    model: str = DEFAULT_MODEL,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = 2,
) -> dict:
    """Run `claude -p` once and return the JSON object it emitted.

    Tools are disabled: the task is text in, JSON out, and a tool call here would
    only be the model trying to read the book off disk instead of the passage it
    was handed.
    """
    last = ""
    for attempt in range(retries + 1):
        ask = prompt if attempt == 0 else (
            f"{prompt}\n\nYour previous reply was not parseable as JSON. Reply with "
            f"the JSON object only, no prose and no code fence.\n\nPrevious reply:\n{last[:500]}"
        )
        proc = subprocess.run(
            ["claude", "-p", "--output-format", "json",
             "--model", model, "--allowed-tools", ""],
            input=ask, capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode != 0:
            raise ClaudeError(f"claude exited {proc.returncode}: {proc.stderr[:300]}")

        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise ClaudeError(f"CLI envelope is not JSON: {e}") from e
        if envelope.get("is_error"):
            raise ClaudeError(f"claude reported an error: {str(envelope)[:300]}")

        last = envelope.get("result") or ""
        try:
            return json.loads(_unfence(last))
        except json.JSONDecodeError:
            continue

    raise ClaudeError(f"no parseable JSON after {retries + 1} attempts: {last[:300]}")
