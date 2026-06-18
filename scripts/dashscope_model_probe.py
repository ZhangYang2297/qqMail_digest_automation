#!/usr/bin/env python3
"""Probe Alibaba Cloud DashScope compatible-mode text-chat model availability.

The script lists OpenAI-compatible models when the endpoint supports it, filters out
code/vision/audio/embedding/image models by default, sorts text models from smaller
or cheaper candidates toward larger ones, then tests candidates with a tiny request.
It cannot reliably read remaining free quota; use model-call failures as fallback
signals and check Alibaba Cloud console for exact quota/billing data.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODELS = [
    "qwen-turbo-latest",
    "qwen-turbo",
    "qwen-plus-latest",
    "qwen-plus",
    "qwen-max-latest",
    "qwen-max",
]
NON_TEXT_MODEL_MARKERS = [
    "vl", "vision", "audio", "asr", "tts", "omni", "coder", "code", "embedding", "rerank",
    "text-embedding", "multimodal", "ocr", "image", "wanx", "video", "stable-diffusion",
    "math", "mt", "translate", "livetranslate", "s2s", "realtime", "deep-research", "deep-search",
    "search", "planning", "dingtalk", "type-api", "longcontext", "long", "character",
]
MODEL_SIZE_ORDER = [
    "0.5b", "1.5b", "3b", "7b", "14b", "32b", "72b", "110b",
    "turbo", "flash", "lite", "plus", "max",
]


def is_text_chat_model(model_id: str) -> bool:
    name = model_id.lower()
    if not name.startswith("qwen"):
        return False
    return not any(marker in name for marker in NON_TEXT_MODEL_MARKERS)


def model_sort_key(model_id: str) -> tuple[int, int, str]:
    name = model_id.lower()
    for index, marker in enumerate(MODEL_SIZE_ORDER):
        if marker in name:
            version_penalty = 1 if "latest" in name else 0
            return index, version_penalty, name
    return len(MODEL_SIZE_ORDER), 1 if "latest" in name else 0, name


def filter_and_sort_models(models: list[str], text_only: bool = True, small_first: bool = True) -> list[str]:
    filtered = [model for model in models if (is_text_chat_model(model) if text_only else True)]
    unique = list(dict.fromkeys(filtered))
    return sorted(unique, key=model_sort_key) if small_first else unique


def read_env_var(name: str) -> str:
    value = os.environ.get(name, "")
    if value or os.name != "nt":
        return value
    try:
        import winreg

        for hive, subkey in [
            (winreg.HKEY_CURRENT_USER, r"Environment"),
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        ]:
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    registry_value, _ = winreg.QueryValueEx(key, name)
                    if registry_value:
                        return os.path.expandvars(str(registry_value))
            except OSError:
                continue
    except ImportError:
        return ""
    return ""


def load_config(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def request_json(url: str, api_key: str, payload: dict[str, Any] | None = None, timeout: int = 30) -> tuple[int, dict[str, Any] | str]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body


def list_models(base_url: str, api_key: str) -> list[str]:
    status, data = request_json(base_url.rstrip("/") + "/models", api_key)
    if status >= 400 or not isinstance(data, dict):
        print(f"models_endpoint_status={status}")
        print(json.dumps(data, ensure_ascii=False, indent=2) if not isinstance(data, str) else data[:500])
        return []
    models: list[str] = []
    for item in data.get("data", []):
        model_id = item.get("id")
        if model_id:
            models.append(model_id)
    return models


def test_model(base_url: str, api_key: str, model: str, timeout: int) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "只回复 OK"}],
        "max_tokens": 8,
        "temperature": 0,
    }
    status, data = request_json(base_url.rstrip("/") + "/chat/completions", api_key, payload, timeout)
    result: dict[str, Any] = {"model": model, "status": status, "ok": False}
    if status < 400 and isinstance(data, dict):
        result["ok"] = True
        result["reply"] = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        result["usage"] = data.get("usage", {})
    else:
        result["error"] = data
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe DashScope text-chat model availability with an API key.")
    parser.add_argument("--config", help="Optional QQ Mail digest config.json to read dashscope settings.")
    parser.add_argument("--api-key-env", default="DASHSCOPE_API_KEY")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--models", nargs="*", help="Models to test. Defaults to config dashscope.models or common Qwen text models.")
    parser.add_argument("--list", action="store_true", help="Try GET /models first and show filtered text models.")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--all-model-types", action="store_true", help="Do not filter out code, vision, embedding, audio, or image models.")
    parser.add_argument("--keep-order", action="store_true", help="Keep API/config order instead of sorting small text models first.")
    args = parser.parse_args()

    config = load_config(args.config)
    dashscope = config.get("summary", {}).get("dashscope", {}) or config.get("dashscope", {})
    base_url = dashscope.get("base_url", args.base_url)
    api_key_env = dashscope.get("api_key_env", args.api_key_env)
    api_key = read_env_var(api_key_env) or dashscope.get("api_key", "")
    if not api_key:
        raise SystemExit(f"Missing API key. Set {api_key_env} or config dashscope.api_key.")

    text_only = not args.all_model_types
    small_first = not args.keep_order
    if args.list:
        models = list_models(base_url, api_key)
        print("text_chat_models_small_first=" if text_only and small_first else "models_from_endpoint=")
        print(json.dumps(filter_and_sort_models(models, text_only=text_only, small_first=small_first), ensure_ascii=False, indent=2))

    candidates = filter_and_sort_models(args.models or dashscope.get("models") or DEFAULT_MODELS, text_only=text_only, small_first=small_first)
    results = [test_model(base_url, api_key, model, args.timeout) for model in candidates]
    print(json.dumps({"base_url": base_url, "candidates": candidates, "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


