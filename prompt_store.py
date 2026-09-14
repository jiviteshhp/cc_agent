# Runtime prompt override for the playground only.
# The phone path always uses prompts.CONVERSATION_PROMPT; this store holds the
# clinician's in-progress edit to that single prompt so they can iterate without
# touching code.
#   update() = Apply (in-memory, affects the next playground conversation)
#   save()   = persist to prompt_override.json (survives a server restart)
#   revert() = drop the override, back to the prompts.py default

import json
import os

import prompts

_OVERRIDE = os.getenv("PROMPT_OVERRIDE_PATH", os.path.join(os.path.dirname(__file__), "prompt_override.json"))

_current = {
    "conversation": prompts.CONVERSATION_PROMPT,
}


def defaults():
    return {
        "conversation": prompts.CONVERSATION_PROMPT,
    }


def get():
    return dict(_current)


def update(conversation):
    # Empty/missing value leaves the current one untouched.
    if conversation and conversation.strip():
        _current["conversation"] = conversation


def save():
    with open(_OVERRIDE, "w", encoding="utf-8") as f:
        json.dump(_current, f, ensure_ascii=False, indent=2)
    print("[prompt_store] saved override")


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
        update(data.get("conversation", ""))
        print("[prompt_store] loaded saved override")
    except Exception as e:
        print(f"[prompt_store] load error: {e}")


_load()
