"""One configured Gemini model for conversation and post-call extraction."""

import asyncio
import json
import os
from contextlib import aclosing

from google import genai
from google.genai import types

import prompts
import voice_diagnostics as diagnostics

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
THINKING = os.getenv("GEMINI_THINKING_LEVEL", "minimal")

FIRST_TEXT_TIMEOUT = float(os.getenv("LLM_FIRST_TEXT_TIMEOUT", "5"))
CHUNK_TIMEOUT = float(os.getenv("LLM_CHUNK_TIMEOUT", "5"))
REQUEST_TIMEOUT = float(os.getenv("LLM_REQUEST_TIMEOUT", "30"))
_gemini = None


class EmptyModelResponse(RuntimeError):
    """Model ended its stream without usable text."""


def _g():
    global _gemini
    if _gemini is None:
        options = types.HttpOptions(
            timeout=int(REQUEST_TIMEOUT * 1000),
            retry_options=types.HttpRetryOptions(attempts=1),
        )
        if os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true":
            _gemini = genai.Client(
                vertexai=True, project=os.environ["GOOGLE_CLOUD_PROJECT"],
                location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
                http_options=options,
            )
        else:
            key = os.getenv("GEMINI_API_KEY", "").strip()
            if not key:
                raise ValueError("GEMINI_API_KEY is missing")
            _gemini = genai.Client(api_key=key, http_options=options)
    return _gemini


def _to_contents(history):
    contents = [{"role": "model" if m["role"] == "assistant" else "user",
                 "parts": [{"text": m["content"]}]} for m in history]
    if contents and contents[0]["role"] == "model":
        contents.insert(0, {"role": "user", "parts": [{"text": "(call connected)"}]})
    return contents


async def stream_reply(history, system=None):
    """One request, with one deadline covering connection through first text."""
    stream = None
    stage = "first_text"
    try:
        deadline = asyncio.get_running_loop().time() + REQUEST_TIMEOUT
        async with asyncio.timeout(min(FIRST_TEXT_TIMEOUT, REQUEST_TIMEOUT)):
            stream = await _g().aio.models.generate_content_stream(
                model=MODEL, contents=_to_contents(history),
                config=types.GenerateContentConfig(
                    system_instruction=system or prompts.CONVERSATION_PROMPT,
                    thinking_config=types.ThinkingConfig(thinking_level=THINKING),
                    max_output_tokens=1024,
                ),
            )
            iterator = stream.__aiter__()
            while True:
                try:
                    first = await anext(iterator)
                except StopAsyncIteration:
                    raise EmptyModelResponse("LLM returned no text") from None
                if first.text:
                    break
        yield first.text
        stage = "stream"
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("LLM turn deadline exceeded")
            try:
                chunk = await asyncio.wait_for(anext(iterator), min(CHUNK_TIMEOUT, remaining))
            except StopAsyncIteration:
                break
            if chunk.text:
                yield chunk.text
    except Exception as exc:
        diagnostics.report_failure("llm", stage, exc)
        raise
    finally:
        if stream is not None:
            await stream.aclose()


async def warm():
    # Same model and deadline as a live turn; no startup retry chain.
    async with aclosing(stream_reply([{"role": "user", "content": "Say namaste."}])) as stream:
        await anext(stream)


def _transcript(history):
    # Preserve role boundaries even when speech contains labels or newlines.
    return json.dumps([{"role": m["role"], "content": m["content"]}
                       for m in history if m["role"] in ("user", "assistant")], ensure_ascii=False)


async def extract(history, *, system=None):
    try:
        return await _extract_once(history, system=system)
    except Exception as exc:
        diagnostics.report_failure("llm", "extraction", exc)
        raise


async def _extract_once(history, *, system=None):
    if not history:
        return {}
    async with asyncio.timeout(REQUEST_TIMEOUT):
        response = await _g().aio.models.generate_content(
            model=MODEL, contents=_transcript(history),
            config=types.GenerateContentConfig(
                system_instruction=prompts.EXTRACT_PROMPT if system is None else system,
                max_output_tokens=4096, thinking_config=types.ThinkingConfig(thinking_level="medium"),
                response_mime_type="application/json",
            ),
        )
    try:
        fields = json.loads(response.text)
    except (ValueError, TypeError):
        raise ValueError("Model returned invalid summary JSON") from None
    if not isinstance(fields, dict):
        raise ValueError("Model summary must be an object")
    allowed = set(prompts.EXTRACT_FIELDS) | {"branch"}
    if any(key not in allowed or not isinstance(value, str) or not value.strip()
           for key, value in fields.items()):
        raise ValueError("Model summary has invalid fields or values")
    if fields.get("laterality", "Right") not in {"Right", "Left", "Both"}:
        raise ValueError("Model summary has invalid laterality")
    if fields.get("branch", "other") not in {"redness", "blurring", "itching", "trauma", "lid", "other"}:
        raise ValueError("Model summary has invalid branch")
    return fields
