from __future__ import annotations

from typing import Optional


UI_LANGUAGE_OPTIONS: list[tuple[str, str]] = [
    ("auto", "Auto (Browser)"),
    ("en", "English"),
    ("ko", "Korean (한국어)"),
    ("ja", "Japanese (日本語)"),
    ("zh-cn", "Chinese Simplified (简体中文)"),
    ("zh-tw", "Chinese Traditional (繁體中文)"),
    ("es", "Spanish (Español)"),
    ("fr", "French (Français)"),
    ("de", "German (Deutsch)"),
]

_VALID_CODES = {code for code, _ in UI_LANGUAGE_OPTIONS}


def normalize_ui_language(code: Optional[str]) -> str:
    if not code:
        return "auto"
    normalized = str(code).strip().lower()
    if normalized in _VALID_CODES:
        return normalized
    return "auto"


def resolve_ui_language(
    preferred_language: Optional[str],
    accept_language: Optional[str] = None,
) -> str:
    preferred = normalize_ui_language(preferred_language)
    if preferred != "auto":
        return preferred

    if not accept_language:
        return "en"

    header = accept_language.lower()
    if "ko" in header:
        return "ko"
    if "ja" in header:
        return "ja"
    if "zh-tw" in header or "zh-hk" in header:
        return "zh-tw"
    if "zh" in header:
        return "zh-cn"
    if "es" in header:
        return "es"
    if "fr" in header:
        return "fr"
    if "de" in header:
        return "de"
    return "en"
