import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from sqlmodel import select

from app.db.engine import get_session, init_db
from app.models.site import Site
from app.services import core_engine


async def _create_site(url: str) -> Site:
    async for session in get_session():
        row = Site(url=url, status="pending")
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def _get_site(site_id: int) -> Site | None:
    async for session in get_session():
        return (await session.exec(select(Site).where(Site.id == site_id))).first()


async def _cleanup_sites(prefix: str) -> None:
    async for session in get_session():
        rows = (
            await session.exec(
                select(Site).where(Site.url.like(f"https://{prefix}%"))
            )
        ).all()
        for row in rows:
            await session.delete(row)
        await session.commit()
        break


def test_clean_html_removes_noise_and_keeps_key_content():
    html = """
    <html>
      <head>
        <title>GhostLink Home</title>
        <meta name="description" content="Best AI optimization platform">
        <style>.hidden { display:none; }</style>
      </head>
      <body>
        <nav>Top Menu</nav>
        <h1>Visible Heading</h1>
        <p>Main content for users and crawlers.</p>
        <p style="display:none">Should be removed</p>
        <footer>Footer text</footer>
        <script>console.log('x')</script>
      </body>
    </html>
    """
    cleaned = core_engine.clean_html(html)

    assert "Top Menu" not in cleaned
    assert "Footer text" not in cleaned
    assert "console.log" not in cleaned
    assert "Should be removed" not in cleaned
    assert "# Title\nGhostLink Home" in cleaned
    assert "## Meta Description\nBest AI optimization platform" in cleaned
    assert "Visible Heading" in cleaned
    assert "Main content for users and crawlers." in cleaned


def test_fetch_page_content_success(monkeypatch: pytest.MonkeyPatch):
    class _Response:
        text = "<html><body>ok</body></html>"

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, _url: str):
            return _Response()

    monkeypatch.setattr(core_engine.httpx, "AsyncClient", _Client)
    result = asyncio.run(core_engine.fetch_page_content("https://example.com"))
    assert result == "<html><body>ok</body></html>"


def test_fetch_page_content_failure_returns_none(monkeypatch: pytest.MonkeyPatch):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, _url: str):
            raise RuntimeError("network failed")

    monkeypatch.setattr(core_engine.httpx, "AsyncClient", _Client)
    result = asyncio.run(core_engine.fetch_page_content("https://example.com"))
    assert result is None


def test_analyze_with_ai_parses_json_object(monkeypatch: pytest.MonkeyPatch):
    payload = {
        "json_ld": {"@context": "https://schema.org", "@type": "Organization"},
        "llms_txt": "GhostLink summary",
        "ai_visibility_score": 84,
    }

    class _Completions:
        async def create(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    monkeypatch.setattr(core_engine, "_openai_client", fake_client)

    result = asyncio.run(core_engine.analyze_with_ai("sample clean text"))
    assert result["json_ld"]["@type"] == "Organization"
    assert result["llms_txt"] == "GhostLink summary"
    assert result["ai_visibility_score"] == 84


def test_analyze_with_ai_handles_provider_error(monkeypatch: pytest.MonkeyPatch):
    class _Completions:
        async def create(self, **kwargs):
            raise RuntimeError("provider down")

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    monkeypatch.setattr(core_engine, "_openai_client", fake_client)

    result = asyncio.run(core_engine.analyze_with_ai("sample clean text"))
    assert result["json_ld"] == {}
    assert result["llms_txt"] == ""
    assert result["ai_visibility_score"] == 0
    assert "provider down" in (result.get("error_msg") or "")


def test_process_site_background_success_updates_site(monkeypatch: pytest.MonkeyPatch):
    prefix = f"pytest_coreeng_{uuid.uuid4().hex[:8]}_"
    url = f"https://{prefix}site.example"
    asyncio.run(init_db())

    async def _fake_fetch(_url: str):
        return """
        <html>
          <head>
            <title>Ghost Product</title>
            <meta name="description" content="AI-ready content layer">
          </head>
          <body>
            <h1>Ghost Product</h1>
            <p>Semantic optimization content.</p>
          </body>
        </html>
        """

    async def _fake_analyze(_clean_text: str):
        return {
            "json_ld": {"@context": "https://schema.org", "@type": "WebSite", "name": "Ghost Product"},
            "llms_txt": "Ghost Product summary for AI agents.",
            "ai_visibility_score": 91,
        }

    monkeypatch.setattr(core_engine, "fetch_page_content", _fake_fetch)
    monkeypatch.setattr(core_engine, "analyze_with_ai", _fake_analyze)

    site = asyncio.run(_create_site(url))
    try:
        assert site.id is not None
        asyncio.run(core_engine.process_site_background(site.id))
        saved = asyncio.run(_get_site(site.id))
        assert saved is not None
        assert saved.status == "active"
        assert saved.error_msg is None
        assert saved.title == "Ghost Product"
        assert saved.meta_description == "AI-ready content layer"
        assert saved.llms_txt == "Ghost Product summary for AI agents."
        assert saved.ai_score == 91
        assert saved.json_ld is not None and "\"@type\": \"WebSite\"" in saved.json_ld
        assert saved.json_ld_content == saved.json_ld
        assert saved.llms_txt_content == saved.llms_txt
    finally:
        asyncio.run(_cleanup_sites(prefix))


def test_process_site_background_aligns_analysis_total_with_ai_score(monkeypatch: pytest.MonkeyPatch):
    prefix = f"pytest_coreeng_{uuid.uuid4().hex[:8]}_"
    url = f"https://{prefix}site.example"
    asyncio.run(init_db())

    async def _fake_fetch(_url: str):
        return """
        <html>
          <head>
            <title>Ghost Product</title>
            <meta name="description" content="AI-ready content layer">
          </head>
          <body>
            <h1>Ghost Product</h1>
            <p>Semantic optimization content.</p>
          </body>
        </html>
        """

    async def _fake_analyze(_clean_text: str):
        return {
            "json_ld": {"@context": "https://schema.org", "@type": "WebSite", "name": "Ghost Product"},
            "llms_txt": "Ghost Product summary for AI agents.",
            "ai_visibility_score": 91,
            "analysis": {
                "scores": {
                    "usability": 88,
                    "seo": 86,
                    "content_quality": 80,
                    "total": 12,
                }
            },
        }

    monkeypatch.setattr(core_engine, "fetch_page_content", _fake_fetch)
    monkeypatch.setattr(core_engine, "analyze_with_ai", _fake_analyze)

    site = asyncio.run(_create_site(url))
    try:
        assert site.id is not None
        asyncio.run(core_engine.process_site_background(site.id))
        saved = asyncio.run(_get_site(site.id))
        assert saved is not None
        assert saved.ai_score == 91
        assert saved.ai_analysis_json is not None
        analysis = json.loads(saved.ai_analysis_json)
        assert analysis["scores"]["total"] == 91
    finally:
        asyncio.run(_cleanup_sites(prefix))


def test_process_site_background_fetch_failure_sets_failed(monkeypatch: pytest.MonkeyPatch):
    prefix = f"pytest_coreeng_{uuid.uuid4().hex[:8]}_"
    url = f"https://{prefix}site.example"
    asyncio.run(init_db())

    async def _fake_fetch(_url: str):
        return None

    monkeypatch.setattr(core_engine, "fetch_page_content", _fake_fetch)
    site = asyncio.run(_create_site(url))
    try:
        assert site.id is not None
        asyncio.run(core_engine.process_site_background(site.id))
        saved = asyncio.run(_get_site(site.id))
        assert saved is not None
        assert saved.status == "failed"
        assert saved.ai_score == 0
        assert saved.error_msg == "Failed to fetch page content."
    finally:
        asyncio.run(_cleanup_sites(prefix))
