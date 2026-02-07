import json
import logging
import re
from datetime import datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup
from openai import AsyncOpenAI
from sqlalchemy.orm import sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.db.engine import engine
from app.models.site import Site


logger = logging.getLogger(__name__)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
}

_openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else None


async def fetch_page_content(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(20.0),
            headers=_BROWSER_HEADERS,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text
    except Exception as exc:
        logger.warning("fetch_page_content failed for %s: %s", url, exc)
        return None


def _extract_metadata(html_content: str) -> tuple[str | None, str | None]:
    soup = BeautifulSoup(html_content, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else None

    meta_description = None
    description_tag = soup.find("meta", attrs={"name": "description"})
    if description_tag and description_tag.get("content"):
        meta_description = description_tag.get("content", "").strip()
    if not meta_description:
        og_tag = soup.find("meta", attrs={"property": "og:description"})
        if og_tag and og_tag.get("content"):
            meta_description = og_tag.get("content", "").strip()
    return title, meta_description


def clean_html(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "html.parser")

    for selector in ("script", "style", "nav", "footer", "svg", "noscript", "template"):
        for tag in soup.select(selector):
            tag.decompose()

    for tag in soup.select('[hidden], [aria-hidden="true"]'):
        tag.decompose()

    for tag in soup.find_all(style=True):
        style = (tag.get("style") or "").replace(" ", "").lower()
        if "display:none" in style or "visibility:hidden" in style:
            tag.decompose()

    title, meta_description = _extract_metadata(str(soup))
    body_node = soup.body if soup.body else soup
    body_text = body_node.get_text(separator="\n", strip=True)
    body_lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    collapsed_body = "\n".join(body_lines)

    parts: list[str] = []
    if title:
        parts.append(f"# Title\n{title}")
    if meta_description:
        parts.append(f"## Meta Description\n{meta_description}")
    parts.append(f"## Body\n{collapsed_body}")
    return "\n\n".join(parts)


def _clamp_score(value: Any) -> int:
    try:
        score = int(float(value))
    except Exception:
        score = 0
    return max(0, min(100, score))


def _normalize_json_ld(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return "{}"
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, (dict, list)):
                return json.dumps(parsed, ensure_ascii=False)
        except Exception:
            pass
        return candidate
    return "{}"


def _infer_schema_type(json_ld_value: Any) -> str:
    if isinstance(json_ld_value, dict):
        return str(json_ld_value.get("@type") or "WebSite")
    if isinstance(json_ld_value, list) and json_ld_value:
        first = json_ld_value[0]
        if isinstance(first, dict):
            return str(first.get("@type") or "WebSite")
    return "WebSite"


def _extract_keywords(*values: str | None, limit: int = 5) -> list[str]:
    seen: set[str] = set()
    keywords: list[str] = []
    for value in values:
        if not value:
            continue
        for token in re.findall(r"[A-Za-z0-9가-힣][A-Za-z0-9가-힣_-]{2,}", value):
            key = token.lower()
            if key in seen:
                continue
            seen.add(key)
            keywords.append(token)
            if len(keywords) >= limit:
                return keywords
    return keywords


def _build_default_analysis(score: int, title: str | None, meta_description: str | None, llms_txt: str) -> dict:
    usability = _clamp_score(score + 4)
    seo = _clamp_score(score)
    content_quality = _clamp_score(score - 4)
    return {
        "scores": {
            "usability": usability,
            "seo": seo,
            "content_quality": content_quality,
            "total": _clamp_score(score),
        },
        "summary_keywords": _extract_keywords(title, meta_description, llms_txt),
        "pros": [
            "Structured schema markup is generated for AI and search engines.",
            "llms.txt summary is available for agent-friendly retrieval.",
        ],
        "cons": [
            "Detailed semantic entity relationships may need manual enrichment.",
        ],
        "recommendations": [
            "Add explicit FAQs and product/service entities in core pages.",
            "Refine headings and metadata with high-intent user questions.",
        ],
        "ghostlink_impact": [
            {
                "title": "AI Readability",
                "description": "Improves machine readability with normalized metadata and schema.",
                "improvement": "+35%",
            },
            {
                "title": "Answer Retrieval",
                "description": "Increases relevance for LLM answer generation with concise llms.txt context.",
                "improvement": "+28%",
            },
        ],
    }


async def analyze_with_ai(clean_text: str) -> dict:
    if not _openai_client:
        return {
            "json_ld": {"@context": "https://schema.org", "@type": "WebSite"},
            "llms_txt": "OpenAI API key is not configured.",
            "ai_visibility_score": 0,
            "error_msg": "OPENAI_API_KEY is not configured",
        }

    try:
        response = await _openai_client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert in Semantic SEO. Analyze the content and generate: "
                        "1. A rich JSON-LD structure (Schema.org). "
                        "2. A concise 'llms.txt' summary for AI agents. "
                        "3. An 'AI Visibility Score' (0-100)."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Return a JSON object with keys: "
                        "`json_ld` (object), `llms_txt` (string), "
                        "`ai_visibility_score` (integer 0-100), "
                        "`analysis` (object with keys: scores{usability,seo,content_quality,total}, "
                        "summary_keywords, pros, cons, recommendations, ghostlink_impact).\n\n"
                        f"{clean_text[:12000]}"
                    ),
                },
            ],
        )
        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        return {
            "json_ld": parsed.get("json_ld", {}),
            "llms_txt": str(parsed.get("llms_txt", "")),
            "ai_visibility_score": _clamp_score(
                parsed.get("ai_visibility_score", parsed.get("ai_score", 0))
            ),
            "analysis": parsed.get("analysis"),
        }
    except Exception as exc:
        logger.exception("analyze_with_ai failed: %s", exc)
        return {
            "json_ld": {},
            "llms_txt": "",
            "ai_visibility_score": 0,
            "error_msg": str(exc),
        }


async def process_site_background(site_id: int, db: AsyncSession | None = None):
    owns_session = db is None
    session = db

    if owns_session:
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        session = async_session()

    assert session is not None
    try:
        site = await session.get(Site, site_id)
        if not site:
            return

        html = await fetch_page_content(site.url)
        if not html:
            site.status = "failed"
            site.error_msg = "Failed to fetch page content."
            site.ai_score = 0
            site.updated_at = datetime.utcnow()
            session.add(site)
            await session.commit()
            return

        title, meta_description = _extract_metadata(html)
        clean_text = clean_html(html)
        ai_result = await analyze_with_ai(clean_text)
        if ai_result.get("error_msg"):
            site.status = "failed"
            site.error_msg = str(ai_result.get("error_msg"))
            site.ai_score = 0
            site.updated_at = datetime.utcnow()
            session.add(site)
            await session.commit()
            return

        json_ld_data = ai_result.get("json_ld", {})
        json_ld_text = _normalize_json_ld(json_ld_data)
        llms_txt = str(ai_result.get("llms_txt", "") or "")
        score = _clamp_score(ai_result.get("ai_visibility_score", 0))
        analysis = ai_result.get("analysis")
        if not isinstance(analysis, dict) or not isinstance(analysis.get("scores"), dict):
            analysis = _build_default_analysis(score, title, meta_description, llms_txt)

        site.title = title
        site.meta_description = meta_description
        site.json_ld = json_ld_text
        site.llms_txt = llms_txt
        site.ai_score = score
        site.status = "active"
        site.error_msg = None
        site.last_scanned_at = datetime.utcnow()
        site.updated_at = datetime.utcnow()

        # Backward compatibility for existing views/services.
        site.json_ld_content = json_ld_text
        site.llms_txt_content = llms_txt
        site.seo_description = meta_description or site.seo_description
        site.schema_type = _infer_schema_type(json_ld_data)
        site.ai_analysis_json = json.dumps(analysis, ensure_ascii=False)

        session.add(site)
        await session.commit()

        try:
            from app.routers.bridge import invalidate_script_cache

            invalidate_script_cache(site.script_id)
        except Exception:
            logger.warning("Failed to invalidate bridge cache for site_id=%s", site_id)
    except Exception as exc:
        logger.exception("process_site_background failed for site_id=%s: %s", site_id, exc)
        try:
            site = await session.get(Site, site_id)
            if site:
                site.status = "failed"
                site.error_msg = str(exc)
                site.ai_score = 0
                site.updated_at = datetime.utcnow()
                session.add(site)
                await session.commit()
        except Exception:
            logger.exception("Failed to write failure state for site_id=%s", site_id)
    finally:
        if owns_session:
            await session.close()
