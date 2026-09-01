# LLM brains for the call:
#   - Gemini Flash drives the live conversation (stream_reply): one system
#     prompt conducts the whole Hindi intake, streamed so the caller can TTS
#     sentence-by-sentence.
#   - Groq gpt-oss does POST-CALL extraction (extract): one pass over the whole
#     transcript -> the doctor's-slip fields as JSON. Kept off the live path so it
#     never adds turn latency.
#
# Gemini capacity is unpredictable per-model: on 2026-07-23, live probing showed
# the standard Flash tier ~50% failing with 503 "high demand" (and one call hung
# 65s before succeeding) while BOTH Lite-tier models below were 100% reliable at
# the exact same time. So stream_reply does not pin one model -- it tries a
# chain, moving to the next entry only if the previous one produced NO text this
# turn (never mid-reply, which would duplicate/garble speech). Groq is the final,
# cross-provider fallback: different infrastructure entirely, so a Gemini-wide
# event can't take it down too. Re-probe live before changing this list --
# NOT_FOUND (model gated for this account) and INVALID_ARGUMENT (e.g. a model
# that rejects an explicit thinking budget) both showed up during testing and
# look nothing like "overloaded," but are handled the same way: skip to the next.

import asyncio
import json
import os

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from groq import AsyncGroq

import prompts

_GEMINI_CHAIN = [
    # (model id, whether it accepts thinking_config -- gemini-3.5-flash-lite
    # 400s on an explicit thinking budget; gemini-3.1-flash-lite accepts it).
    ("gemini-3.1-flash-lite", True),
    ("gemini-3.5-flash-lite", False),
]
_GROQ_FALLBACK_MODEL = "openai/gpt-oss-120b"  # live-conversation last resort
_EXTRACT_MODEL = "openai/gpt-oss-120b"        # post-call slip extraction (unchanged)

# Bounds the wait for a model's FIRST token. Google can silently queue a request
# under load instead of erroring (the 65s hang above), so this protects turn
# latency even when Gemini doesn't 503. Not applied to later chunks: once a
# reply is already flowing, abandoning it mid-sentence would be worse than a
# rare slow gap, and switching models mid-reply isn't safe (see above).
_ATTEMPT_TIMEOUT = 5.0

_gemini = None
_groq = None


def _g():
    global _gemini
    if _gemini is None:
        _gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _gemini


def _groq_client():
    global _groq
    if _groq is None:
        _groq = AsyncGroq(api_key=os.environ["GROQ_API_KEY"],
                          timeout=30.0, max_retries=2)
    return _groq


def _to_contents(history):
    # Map our [{role: user|assistant, content}] to Gemini contents (assistant ->
    # model). Gemini expects the turn list to start with a user turn, so if the
    # first item is the fixed greeting (a model turn), prepend a neutral anchor.
    contents = [{"role": "model" if m["role"] == "assistant" else "user",
                 "parts": [{"text": m["content"]}]}
                for m in history]
    if contents and contents[0]["role"] == "model":
        contents.insert(0, {"role": "user", "parts": [{"text": "(call connected)"}]})
    return contents


async def _gemini_attempt(model, contents, config):
    # One attempt against one model. Only the wait for the FIRST token is
    # bounded (see _ATTEMPT_TIMEOUT) -- once tokens are flowing we trust the
    # stream through to completion.
    stream = await asyncio.wait_for(
        _g().aio.models.generate_content_stream(model=model, contents=contents, config=config),
        timeout=_ATTEMPT_TIMEOUT)
    it = stream.__aiter__()
    try:
        first = await asyncio.wait_for(it.__anext__(), timeout=_ATTEMPT_TIMEOUT)
    except StopAsyncIteration:
        return
    if first.text:
        yield first.text
    async for chunk in it:
        if chunk.text:
            yield chunk.text


async def _groq_stream_reply(history, system):
    # Cross-provider fallback, same shape as the old pre-Gemini implementation.
    # Groq/OpenAI-style roles already match ours (user/assistant), so no
    # remapping is needed here (unlike _to_contents for Gemini).
    messages = [{"role": "system", "content": system}] + [
        {"role": m["role"], "content": m["content"]} for m in history]
    stream = await _groq_client().chat.completions.create(
        model=_GROQ_FALLBACK_MODEL,
        messages=messages,
        max_tokens=256,
        temperature=0.3,
        reasoning_effort="low",
        stream=True,
    )
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


async def stream_reply(history, system=None):
    # Stream one turn over the whole conversation. Tries each model in
    # _GEMINI_CHAIN in order, then Groq, yielding text deltas as they arrive so
    # the caller can synthesize speech sentence-by-sentence. Only advances to the
    # next backend if the previous one produced NO text for this turn; a failure
    # after speech has already started is raised as-is (the caller -- agent.py --
    # speaks an apology rather than risk mixed/duplicated speech from switching
    # backends mid-reply).
    sys_prompt = system or prompts.CONVERSATION_PROMPT
    contents = _to_contents(history)

    for model, use_thinking in _GEMINI_CHAIN:
        cfg = dict(system_instruction=sys_prompt, temperature=0.3, max_output_tokens=256)
        if use_thinking:
            cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        config = types.GenerateContentConfig(**cfg)
        yielded = False
        try:
            async for piece in _gemini_attempt(model, contents, config):
                yielded = True
                yield piece
            if yielded:
                return
            print(f"[llm] {model} returned no text, trying next")
        except asyncio.TimeoutError:
            if yielded:
                raise
            print(f"[llm] {model} timed out after {_ATTEMPT_TIMEOUT}s, trying next")
        except genai_errors.APIError as e:
            if yielded:
                raise
            print(f"[llm] {model} {getattr(e, 'status', '?')}, trying next: {e}")

    print(f"[llm] all Gemini models failed this turn; falling back to Groq {_GROQ_FALLBACK_MODEL}")
    async for piece in _groq_stream_reply(history, sys_prompt):
        yield piece


async def warm():
    # A tiny call at startup so the first real turn isn't a cold start. Only
    # warms the primary model -- if it's unreachable, the chain in stream_reply
    # handles that live; this is purely to avoid a cold-start delay.
    model, use_thinking = _GEMINI_CHAIN[0]
    cfg = dict(max_output_tokens=1)
    if use_thinking:
        cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    for attempt in range(3):
        try:
            await _g().aio.models.generate_content(
                model=model,
                contents=[{"role": "user", "parts": [{"text": "ok"}]}],
                config=types.GenerateContentConfig(**cfg),
            )
            return
        except Exception as e:
            print(f"[llm] warm attempt {attempt+1} failed: {e}")


def _transcript(history):
    # Render the conversation as plain text for the post-call extractor.
    lines = []
    for m in history:
        who = "Assistant" if m["role"] == "assistant" else "Patient"
        lines.append(f"{who}: {m['content']}")
    return "\n".join(lines)


async def extract(history):
    # POST-CALL: read the whole Hindi transcript once and return the doctor's-slip
    # fields as JSON. Returns {} on failure. Off the live path (no turn latency).
    if not history:
        return {}
    resp = await _groq_client().chat.completions.create(
        model=_EXTRACT_MODEL,
        messages=[
            {"role": "system", "content": prompts.EXTRACT_PROMPT},
            {"role": "user", "content": _transcript(history)},
        ],
        max_tokens=500,
        temperature=0,
        reasoning_effort="low",
        response_format={"type": "json_object"},
    )
    try:
        return json.loads(resp.choices[0].message.content)
    except (ValueError, AttributeError):
        return {}
