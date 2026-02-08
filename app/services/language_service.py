from __future__ import annotations

from urllib.parse import urlparse


LANGUAGE_OPTIONS: list[tuple[str, str]] = [
    ("auto", "Auto (Country Default)"),
    ("en", "English"),
    ("ko", "Korean (한국어)"),
    ("ja", "Japanese (日本語)"),
    ("zh-cn", "Chinese Simplified (简体中文)"),
    ("zh-tw", "Chinese Traditional (繁體中文)"),
    ("es", "Spanish (Español)"),
    ("fr", "French (Français)"),
    ("de", "German (Deutsch)"),
    ("pt-br", "Portuguese BR (Português)"),
    ("it", "Italian (Italiano)"),
    ("ru", "Russian (Русский)"),
    ("ar", "Arabic (العربية)"),
    ("hi", "Hindi (हिन्दी)"),
    ("vi", "Vietnamese (Tiếng Việt)"),
    ("th", "Thai (ไทย)"),
    ("id", "Indonesian (Bahasa Indonesia)"),
    ("tr", "Turkish (Türkçe)"),
    ("nl", "Dutch (Nederlands)"),
    ("pl", "Polish (Polski)"),
]

SUPPORTED_LANGUAGE_CODES = {code for code, _ in LANGUAGE_OPTIONS}

LANGUAGE_LABELS: dict[str, str] = dict(LANGUAGE_OPTIONS)

PROMPT_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "ko": "Korean",
    "ja": "Japanese",
    "zh-cn": "Simplified Chinese",
    "zh-tw": "Traditional Chinese",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt-br": "Brazilian Portuguese",
    "it": "Italian",
    "ru": "Russian",
    "ar": "Arabic",
    "hi": "Hindi",
    "vi": "Vietnamese",
    "th": "Thai",
    "id": "Indonesian",
    "tr": "Turkish",
    "nl": "Dutch",
    "pl": "Polish",
}

COUNTRY_DEFAULT_LANGUAGE: dict[str, str] = {
    "kr": "ko",
    "jp": "ja",
    "cn": "zh-cn",
    "tw": "zh-tw",
    "hk": "zh-tw",
    "mo": "zh-tw",
    "es": "es",
    "mx": "es",
    "ar": "es",
    "cl": "es",
    "co": "es",
    "pe": "es",
    "fr": "fr",
    "de": "de",
    "at": "de",
    "ch": "de",
    "it": "it",
    "br": "pt-br",
    "pt": "pt-br",
    "ru": "ru",
    "ua": "ru",
    "tr": "tr",
    "sa": "ar",
    "ae": "ar",
    "eg": "ar",
    "qa": "ar",
    "kw": "ar",
    "bh": "ar",
    "om": "ar",
    "jo": "ar",
    "lb": "ar",
    "ma": "ar",
    "dz": "ar",
    "tn": "ar",
    "in": "hi",
    "vn": "vi",
    "th": "th",
    "id": "id",
    "nl": "nl",
    "be": "nl",
    "pl": "pl",
    "us": "en",
    "uk": "en",
    "gb": "en",
    "ca": "en",
    "au": "en",
    "nz": "en",
    "ie": "en",
    "sg": "en",
}


def normalize_language_preference(value: str | None) -> str:
    candidate = (value or "").strip().lower()
    if not candidate:
        return "auto"

    aliases = {
        "english": "en",
        "korean": "ko",
        "japanese": "ja",
        "chinese": "zh-cn",
        "chinese-simplified": "zh-cn",
        "chinese-traditional": "zh-tw",
        "spanish": "es",
        "french": "fr",
        "german": "de",
        "portuguese": "pt-br",
        "portuguese-br": "pt-br",
        "italian": "it",
        "russian": "ru",
        "arabic": "ar",
        "hindi": "hi",
        "vietnamese": "vi",
        "thai": "th",
        "indonesian": "id",
        "turkish": "tr",
        "dutch": "nl",
        "polish": "pl",
        "zh_cn": "zh-cn",
        "zh_tw": "zh-tw",
        "pt_br": "pt-br",
    }
    normalized = aliases.get(candidate, candidate)
    if normalized in SUPPORTED_LANGUAGE_CODES:
        return normalized
    return "auto"


def language_label(code: str | None) -> str:
    normalized = normalize_language_preference(code)
    return LANGUAGE_LABELS.get(normalized, LANGUAGE_LABELS["en"])


def prompt_language_name(code: str | None) -> str:
    normalized = normalize_language_preference(code)
    if normalized == "auto":
        return PROMPT_LANGUAGE_NAMES["en"]
    return PROMPT_LANGUAGE_NAMES.get(normalized, PROMPT_LANGUAGE_NAMES["en"])


def _normalize_locale_to_language_code(raw_locale: str | None) -> str | None:
    if not raw_locale:
        return None
    locale = raw_locale.strip().lower().replace("_", "-")
    if not locale:
        return None

    if locale.startswith("zh"):
        if any(part in locale for part in ("tw", "hk", "mo", "hant")):
            return "zh-tw"
        return "zh-cn"
    if locale.startswith("pt-br"):
        return "pt-br"

    base = locale.split("-")[0]
    if base in SUPPORTED_LANGUAGE_CODES:
        return base
    if base == "pt":
        return "pt-br"
    return None


def infer_language_from_accept_language(accept_language: str | None) -> str | None:
    if not accept_language:
        return None
    for chunk in accept_language.split(","):
        token = chunk.split(";")[0].strip()
        normalized = _normalize_locale_to_language_code(token)
        if normalized:
            return normalized
    return None


def infer_country_code_from_url(url: str | None) -> str | None:
    if not url:
        return None
    hostname = (urlparse(url).hostname or "").strip().lower()
    if not hostname:
        return None
    parts = [part for part in hostname.split(".") if part]
    if len(parts) < 2:
        return None
    last = parts[-1]
    if len(last) == 2 and last.isalpha():
        return last
    return None


def infer_language_from_url(url: str | None) -> str | None:
    country = infer_country_code_from_url(url)
    if not country:
        return None
    return COUNTRY_DEFAULT_LANGUAGE.get(country)


def resolve_effective_language_code(
    preferred_language: str | None,
    site_url: str | None,
    accept_language: str | None = None,
) -> str:
    preferred = normalize_language_preference(preferred_language)
    if preferred != "auto":
        return preferred

    from_url = infer_language_from_url(site_url)
    if from_url:
        return from_url

    from_accept_header = infer_language_from_accept_language(accept_language)
    if from_accept_header:
        return from_accept_header

    return "en"

