"""AGI Phone plugin — gives Hermes control of a connected Android phone.

The phone runs a computer-use AI agent (screenshot -> action -> execute).
This plugin wraps the FCM relay that dispatches prompts to the phone and
reads back results.

Install:
    hermes plugins install stevekfrey/agi-phone-plugin

Configure:
    PHONE_RELAY_URL=https://mobile-claw-mcp-server.vercel.app
"""

import json
import logging
import os
import time

logger = logging.getLogger(__name__)

_DEFAULT_RELAY_URL = "https://mobile-claw-mcp-server.vercel.app"


def _get_relay_url() -> str:
    return os.getenv("PHONE_RELAY_URL", _DEFAULT_RELAY_URL).rstrip("/")


def _check_available() -> bool:
    return bool(_get_relay_url())


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def _handle_send_to_phone(args: dict, **kwargs) -> str:
    import httpx

    prompt = args.get("prompt", "").strip()
    if not prompt:
        return json.dumps({"error": "Missing required parameter: prompt"})

    try:
        resp = httpx.post(
            f"{_get_relay_url()}/api/send",
            json={"prompt": prompt},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return json.dumps({
            "status": "sent",
            "request_id": data.get("request_id"),
            "prompt": prompt,
            "message": "Prompt sent to phone. Use get_phone_result to check the outcome.",
        })
    except Exception as e:
        logger.error("send_to_phone error: %s", e)
        return json.dumps({"error": f"Failed to send prompt to phone: {e}"})


def _handle_get_phone_result(args: dict, **kwargs) -> str:
    import httpx

    request_id = args.get("request_id", "").strip()
    if not request_id:
        return json.dumps({"error": "Missing required parameter: request_id"})

    try:
        resp = httpx.get(
            f"{_get_relay_url()}/api/result",
            params={"id": request_id},
            timeout=15,
        )
        if resp.status_code == 404:
            return json.dumps({
                "status": "not_found",
                "message": f"No result for {request_id}. May still be running or expired.",
            })
        resp.raise_for_status()
        return json.dumps(resp.json())
    except Exception as e:
        logger.error("get_phone_result error: %s", e)
        return json.dumps({"error": f"Failed to check phone result: {e}"})


def _handle_phone_do(args: dict, **kwargs) -> str:
    import httpx

    prompt = args.get("prompt", "").strip()
    if not prompt:
        return json.dumps({"error": "Missing required parameter: prompt"})

    timeout_seconds = min(args.get("timeout", 120), 300)
    relay_url = _get_relay_url()

    # Send
    try:
        send_resp = httpx.post(
            f"{relay_url}/api/send",
            json={"prompt": prompt},
            timeout=15,
        )
        send_resp.raise_for_status()
        request_id = send_resp.json().get("request_id")
    except Exception as e:
        return json.dumps({"error": f"Failed to send prompt to phone: {e}"})

    # Poll
    deadline = time.time() + timeout_seconds
    poll_interval = 2
    last_status = "pending"

    while time.time() < deadline:
        time.sleep(poll_interval)
        try:
            r = httpx.get(
                f"{relay_url}/api/result",
                params={"id": request_id},
                timeout=10,
            )
            if r.status_code == 404:
                continue
            data = r.json()
            last_status = data.get("status", "unknown")
            if last_status in ("completed", "failed"):
                return json.dumps(data)
        except Exception:
            pass
        poll_interval = min(poll_interval * 1.5, 10)

    return json.dumps({
        "status": "timeout",
        "request_id": request_id,
        "last_status": last_status,
        "message": f"Phone did not report result within {timeout_seconds}s.",
    })


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

SEND_TO_PHONE_SCHEMA = {
    "name": "send_to_phone",
    "description": (
        "Send an instruction to the connected Android phone. The phone's AI agent "
        "will execute it using computer-use (opening apps, tapping, typing, etc). "
        "Returns immediately with a request_id. Use get_phone_result to check the outcome. "
        "Examples: 'Open Uber and request a ride to 123 Main St', 'Search YouTube for funny cats'."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The instruction for the phone agent to execute.",
            },
        },
        "required": ["prompt"],
    },
}

GET_PHONE_RESULT_SCHEMA = {
    "name": "get_phone_result",
    "description": (
        "Check the result of a previously sent phone instruction. "
        "Use the request_id returned by send_to_phone."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "request_id": {
                "type": "string",
                "description": "The request_id from a previous send_to_phone call.",
            },
        },
        "required": ["request_id"],
    },
}

PHONE_DO_SCHEMA = {
    "name": "phone_do",
    "description": (
        "Send an instruction to the phone and wait for the result. "
        "Combines send + poll into one call. Use when you need the outcome before proceeding. "
        "Examples: 'Call an Uber to 123 Main St', 'Check my latest email'."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The instruction for the phone agent to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds to wait for result (default 120, max 300).",
                "default": 120,
            },
        },
        "required": ["prompt"],
    },
}


# ---------------------------------------------------------------------------
# System prompt injection
# ---------------------------------------------------------------------------

_PHONE_CONTEXT = """You have a connected Android phone that you can control remotely. \
When the user asks you to do something on their phone (open an app, send a message, \
order a ride, check something on screen, etc.), use the phone_do tool. \
For fire-and-forget tasks where you don't need the result, use send_to_phone instead. \
The phone agent uses computer-vision to tap, type, and navigate — treat it like \
a capable human operating the phone on the user's behalf."""


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------

def register(ctx):
    """Called by Hermes plugin loader on startup."""

    # Tools
    ctx.register_tool(
        name="send_to_phone",
        toolset="phone",
        schema=SEND_TO_PHONE_SCHEMA,
        handler=_handle_send_to_phone,
        check_fn=_check_available,
        emoji="\U0001f4f1",
    )

    ctx.register_tool(
        name="get_phone_result",
        toolset="phone",
        schema=GET_PHONE_RESULT_SCHEMA,
        handler=_handle_get_phone_result,
        check_fn=_check_available,
        emoji="\U0001f4f1",
    )

    ctx.register_tool(
        name="phone_do",
        toolset="phone",
        schema=PHONE_DO_SCHEMA,
        handler=_handle_phone_do,
        check_fn=_check_available,
        emoji="\U0001f4f1",
    )

    # Inject phone awareness into every conversation
    ctx.register_hook("pre_llm_call", _inject_phone_context)

    logger.info("agi-phone plugin registered (relay: %s)", _get_relay_url())


def _inject_phone_context(**kwargs):
    """pre_llm_call hook — tells Hermes it has a phone available."""
    if _check_available():
        return {"context": _PHONE_CONTEXT}
    return None
