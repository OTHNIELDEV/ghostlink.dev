from fastapi.testclient import TestClient

from app.main import app


def test_footer_links_are_real_routes():
    with TestClient(app) as client:
        landing = client.get("/")
        assert landing.status_code == 200

        expected_hrefs = [
            "/features",
            "/footer/pricing",
            "/footer/integrations",
            "/footer/changelog",
            "/footer/documentation",
            "/footer/blog",
            "/footer/community",
            "/footer/help-center",
            "/footer/api-reference",
            "/footer/status",
            "/footer/about",
            "/footer/careers",
            "/footer/legal",
            "/footer/contact",
            "/footer/privacy",
            "/footer/terms",
        ]
        for href in expected_hrefs:
            assert f'href="{href}"' in landing.text


def test_footer_detail_routes_render():
    pages = [
        ("/features", "Built for the"),
        ("/footer/pricing", "Pricing and Packaging"),
        ("/footer/integrations", "Integration Paths"),
        ("/footer/changelog", "Release and Changelog"),
        ("/footer/documentation", "Documentation Hub"),
        ("/footer/blog", "Insights and Playbooks"),
        ("/footer/community", "Community Workspace"),
        ("/footer/help-center", "Help Center"),
        ("/footer/api-reference", "API Reference"),
        ("/footer/status", "System Status"),
        ("/footer/about", "About GhostLink"),
        ("/footer/careers", "Careers"),
        ("/footer/legal", "Legal Overview"),
        ("/footer/contact", "Contact and Escalation"),
        ("/footer/privacy", "Privacy Policy"),
        ("/footer/terms", "Terms of Service"),
    ]

    with TestClient(app) as client:
        for path, marker in pages:
            response = client.get(path)
            assert response.status_code == 200
            assert marker in response.text

        changelog = client.get("/footer/changelog")
        assert changelog.status_code == 200
        assert "Live Update Timeline" in changelog.text
        assert "Optimization Reward Loop v2 Baseline Delta" in changelog.text

        status = client.get("/footer/status")
        assert status.status_code == 200
        assert "Live Update Timeline" in status.text
        assert "API Gateway" in status.text
