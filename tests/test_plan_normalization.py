from app.billing.plans import get_plan, is_valid_plan_code, normalize_plan_code
import app.services.stripe_service as stripe_service_module


def test_business_alias_normalizes_to_pro():
    assert is_valid_plan_code("business") is True
    assert normalize_plan_code("business") == "pro"
    assert get_plan("business").code == "pro"


def test_unknown_plan_falls_back_to_free():
    assert is_valid_plan_code("unknown-plan") is False
    assert normalize_plan_code("unknown-plan") == "free"


def test_stripe_business_price_maps_back_to_pro(monkeypatch):
    monkeypatch.setattr(stripe_service_module.settings, "STRIPE_PRICE_BUSINESS_MONTH", "price_business_month")
    monkeypatch.setattr(stripe_service_module.settings, "STRIPE_PRICE_BUSINESS_YEAR", "")
    monkeypatch.setattr(stripe_service_module.settings, "STRIPE_PRICE_BUSINESS", "")
    assert stripe_service_module.stripe_service.get_plan_code_for_price_id("price_business_month") == "pro"
