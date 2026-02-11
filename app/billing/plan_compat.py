from __future__ import annotations

from typing import Any, Iterable

from app.models.billing import Plan, PlanFeature

import app.billing.plans as _plans


_FALLBACK_ALIASES: dict[str, str] = {
    "business": "pro",
}


def _to_lower(value: Any) -> str:
    return str(value or "").strip().lower()


def _get_plan_aliases() -> dict[str, str]:
    aliases = getattr(_plans, "PLAN_ALIASES", {})
    normalized: dict[str, str] = {}
    if isinstance(aliases, dict):
        for key, target in aliases.items():
            key_norm = _to_lower(key)
            target_norm = _to_lower(target)
            if key_norm and target_norm:
                normalized[key_norm] = target_norm

    for key, target in _FALLBACK_ALIASES.items():
        normalized.setdefault(key, target)
    return normalized


def _get_plan_config() -> dict[str, dict[str, Any]]:
    config = getattr(_plans, "PLAN_CONFIG", {})
    return config if isinstance(config, dict) else {}


def _normalize_codes(raw_codes: Any) -> tuple[str, ...]:
    if not isinstance(raw_codes, (tuple, list)):
        return tuple()
    normalized: list[str] = []
    for code in raw_codes:
        code_norm = _to_lower(code)
        if code_norm:
            normalized.append(code_norm)
    return tuple(normalized)


DEFAULT_PLAN_CODE = _to_lower(getattr(_plans, "DEFAULT_PLAN_CODE", "free")) or "free"


def normalize_plan_code(plan_code: str | None, fallback: str = DEFAULT_PLAN_CODE) -> str:
    fn = getattr(_plans, "normalize_plan_code", None)
    if callable(fn):
        try:
            return _to_lower(fn(plan_code, fallback=fallback)) or fallback
        except TypeError:
            try:
                normalized = _to_lower(fn(plan_code))
                return normalized or fallback
            except Exception:
                pass

    candidate = _to_lower(plan_code)
    if not candidate:
        return fallback

    candidate = _get_plan_aliases().get(candidate, candidate)
    if candidate in _get_plan_config():
        return candidate
    return fallback


def is_valid_plan_code(plan_code: str | None) -> bool:
    fn = getattr(_plans, "is_valid_plan_code", None)
    if callable(fn):
        try:
            return bool(fn(plan_code))
        except Exception:
            pass

    candidate = _to_lower(plan_code)
    if not candidate:
        return False

    aliases = _get_plan_aliases()
    config = _get_plan_config()
    return candidate in config or candidate in aliases


def _coerce_feature_list(raw_features: Any) -> list[PlanFeature]:
    if isinstance(raw_features, (str, bytes, dict)) or not isinstance(raw_features, Iterable):
        return []

    features: list[PlanFeature] = []
    for item in raw_features:
        if isinstance(item, PlanFeature):
            features.append(item)
            continue
        if isinstance(item, dict):
            features.append(
                PlanFeature(
                    code=_to_lower(item.get("code")) or "feature",
                    name=str(item.get("name") or item.get("code") or "Feature"),
                    description=str(item.get("description") or ""),
                    included=bool(item.get("included", True)),
                )
            )
            continue

        code = _to_lower(getattr(item, "code", "")) or "feature"
        features.append(
            PlanFeature(
                code=code,
                name=str(getattr(item, "name", code)),
                description=str(getattr(item, "description", "")),
                included=bool(getattr(item, "included", True)),
            )
        )
    return features


def get_plan(plan_code: str | None) -> Plan:
    fn = getattr(_plans, "get_plan", None)
    if callable(fn):
        try:
            return fn(plan_code)
        except Exception:
            pass

    config_map = _get_plan_config()
    normalized = normalize_plan_code(plan_code)
    config = config_map.get(normalized)
    if not isinstance(config, dict):
        config = config_map.get(DEFAULT_PLAN_CODE, {})

    limits = config.get("limits")
    if not isinstance(limits, dict):
        limits = {}

    return Plan(
        code=normalized,
        name=str(config.get("name") or normalized.title()),
        description=str(config.get("description") or ""),
        price_monthly=int(config.get("price_monthly") or 0),
        price_yearly=int(config.get("price_yearly") or 0),
        currency=str(config.get("currency") or "usd"),
        features=_coerce_feature_list(config.get("features")),
        limits=limits,
        is_popular=bool(config.get("is_popular", False)),
        is_enterprise=bool(config.get("is_enterprise", False)),
    )


def get_all_plans(public_only: bool = False) -> list[Plan]:
    fn = getattr(_plans, "get_all_plans", None)
    if callable(fn):
        try:
            return list(fn(public_only=public_only))
        except TypeError:
            plans = list(fn())
            if public_only:
                public_codes = set(_normalize_codes(getattr(_plans, "PUBLIC_PLAN_CODES", ())))
                if public_codes:
                    return [plan for plan in plans if _to_lower(getattr(plan, "code", "")) in public_codes]
                return [plan for plan in plans if _to_lower(getattr(plan, "code", "")) != DEFAULT_PLAN_CODE]
            return plans
        except Exception:
            pass

    if public_only:
        codes = _normalize_codes(getattr(_plans, "PUBLIC_PLAN_CODES", ()))
    else:
        internal_codes = _normalize_codes(getattr(_plans, "INTERNAL_PLAN_CODES", ("free",)))
        public_codes = _normalize_codes(getattr(_plans, "PUBLIC_PLAN_CODES", ()))
        codes = internal_codes + public_codes

    if not codes:
        codes = tuple(_get_plan_config().keys())

    return [get_plan(code) for code in codes]


def get_public_plans() -> list[Plan]:
    fn = getattr(_plans, "get_public_plans", None)
    if callable(fn):
        try:
            return list(fn())
        except Exception:
            pass
    return get_all_plans(public_only=True)


def get_plan_limit(plan_code: str, limit_name: str) -> int:
    fn = getattr(_plans, "get_plan_limit", None)
    if callable(fn):
        try:
            return int(fn(plan_code, limit_name))
        except Exception:
            pass

    plan = get_plan(plan_code)
    raw_value = plan.limits.get(limit_name, 0) if isinstance(plan.limits, dict) else 0
    try:
        return int(raw_value)
    except Exception:
        return 0


def can_use_feature(plan_code: str, feature_code: str) -> bool:
    fn = getattr(_plans, "can_use_feature", None)
    if callable(fn):
        try:
            return bool(fn(plan_code, feature_code))
        except Exception:
            pass

    feature_code_norm = _to_lower(feature_code)
    plan = get_plan(plan_code)
    for feature in plan.features:
        if _to_lower(feature.code) == feature_code_norm:
            return bool(feature.included)
    return False


__all__ = [
    "DEFAULT_PLAN_CODE",
    "can_use_feature",
    "get_all_plans",
    "get_plan",
    "get_plan_limit",
    "get_public_plans",
    "is_valid_plan_code",
    "normalize_plan_code",
]
