from fastapi.testclient import TestClient

from app.main import app


def test_billing_plans_exposes_three_public_tiers():
    with TestClient(app) as client:
        response = client.get("/billing/plans")

    assert response.status_code == 200
    payload = response.json()
    plans = payload.get("plans", [])
    codes = [row.get("code") for row in plans]
    assert codes == ["starter", "pro", "enterprise"]


def test_billing_plans_omits_legacy_and_internal_tiers():
    with TestClient(app) as client:
        response = client.get("/billing/plans")

    assert response.status_code == 200
    payload = response.json()
    codes = {row.get("code") for row in payload.get("plans", [])}
    assert "free" not in codes
    assert "business" not in codes
