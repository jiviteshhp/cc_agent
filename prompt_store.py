# Runtime conversation/extraction prompts and ASR settings for the playground.
# Phone keeps default prompts/ASR, and reads the saved native first message.
#   update() = Apply (in-memory, affects the next playground conversation)
#   save()   = persist to prompt_override.json (survives a server restart)
#   revert() = drop the override, back to the prompts.py default

import json
import os
from copy import deepcopy

import prompts
from stt_stream import validate_vocabulary

_OVERRIDE = os.getenv("PROMPT_OVERRIDE_PATH", os.path.join(os.path.dirname(__file__), "prompt_override.json"))

ASR_CONTEXT = "Hindi and Hinglish eye-clinic intake. The caller may describe eye discomfort, vision changes, previous treatment and regular medicines. Recognize the words actually spoken; do not add symptoms, diagnoses, medicines or answers that were not said."
ASR_KEYTERMS = ["आंख", "दाईं आंख", "बाईं आंख", "धुंधलापन", "जलन", "खुजली",
                "लालपन", "पानी आना", "चश्मे का नंबर", "मोतियाबिंद", "ग्लूकोमा", "रेटिना"]


def defaults():
    return {
        "conversation": prompts.CONVERSATION_PROMPT,
        "s2s_conversation": prompts.S2S_CONVERSATION_PROMPT,
        "s2s_first_message": prompts.GREETING,
        "extraction": prompts.EXTRACT_PROMPT,
        "asr_prompt": ASR_CONTEXT,
        "asr_keyterms": list(ASR_KEYTERMS),
    }


_current = defaults()


def get():
    return deepcopy(_current)


def validate_updates(values):
    if not isinstance(values, dict):
        raise ValueError("Settings must be an object")
    updates = {}
    for key in ("conversation", "s2s_conversation", "extraction"):
        if key in values:
            text = values[key]
            if not isinstance(text, str) or not 1 <= len(text.strip()) <= 16000:
                raise ValueError(f"{key.capitalize()} prompt must contain 1–16000 characters")
            updates[key] = text.strip()
    if "s2s_first_message" in values:
        text = values["s2s_first_message"]
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 500:
            raise ValueError("Speech-to-speech first message must contain 1–500 characters")
        updates["s2s_first_message"] = text.strip()
    if "asr_prompt" in values or "asr_keyterms" in values:
        hint, terms = validate_vocabulary(values.get("asr_prompt", ""), values.get("asr_keyterms", []))
        if "asr_prompt" in values:
            updates["asr_prompt"] = hint
        if "asr_keyterms" in values:
            updates["asr_keyterms"] = terms
    return updates


def update(conversation=None, **settings):
    # Empty/missing value leaves the current one untouched.
    if conversation and conversation.strip():
        settings["conversation"] = conversation
    _current.update(validate_updates(settings))


def save():
    # Phone and website processes share this file. Replace atomically so a new
    # phone call never observes a partially written first-message setting.
    with open(_OVERRIDE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(_current, f, ensure_ascii=False, indent=2)
    os.replace(_OVERRIDE + ".tmp", _OVERRIDE)
    print("[prompt_store] saved override")


def saved_first_message():
    """Read each phone call's saved opening without importing unsaved web edits."""
    try:
        with open(_OVERRIDE, encoding="utf-8") as f:
            value = json.load(f).get("s2s_first_message", prompts.GREETING)
        return validate_updates({"s2s_first_message": value})["s2s_first_message"]
    except (OSError, ValueError, AttributeError):
        return prompts.GREETING


def revert():
    _current.update(defaults())
    if os.path.exists(_OVERRIDE):
        os.remove(_OVERRIDE)
    print("[prompt_store] reverted to default")


def _load():
    if not os.path.exists(_OVERRIDE):
        return
    try:
        with open(_OVERRIDE, encoding="utf-8") as f:
            data = json.load(f)
        _current.update(validate_updates(data))
        print("[prompt_store] loaded saved override")
    except Exception as e:
        print(f"[prompt_store] load error: {type(e).__name__}")


_load()
