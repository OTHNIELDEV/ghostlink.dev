import trafilatura
from bs4 import BeautifulSoup
from openai import AsyncOpenAI
import json
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

from app.services.crawler import crawler_service

class AIService:
    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY
        if self.api_key:
            self.client = AsyncOpenAI(api_key=self.api_key)
        else:
            self.client = None
            logger.warning("OPENAI_API_KEY not found. Running in MOCK mode.")

    async def generate_assets(self, url: str, language: str = "English", custom_instruction: str = None):
        """
        1. Crawl & Extract content (Robust).
        2. Classify Site Type.
        3. Generate JSON-LD & RAG-Optimized llms.txt with Custom Instructions.
        """
        
        try:
            # Use the new robust crawler
            crawl_result = await crawler_service.crawl_and_extract(url)
            content = crawl_result["content"]
            
            if not content:
                return self._get_error_response("No content detected.")

            if not self.client:
                return self._get_mock_response(url)

            # --- Step 1: Classification & JSON-LD Construction ---
            schema_prompt = """
            You are a semantic web expert. Analyze the website content and determine its category:
            - 'E-commerce' -> Generate 'Product' schema.
            - 'Real Estate' -> Generate 'RealEstateListing' schema.
            - 'Blog/News' -> Generate 'Article' or 'BlogPosting' schema.
            - 'Corporate' -> Generate 'Organization' schema.

            Return a JSON object with:
            1. "schema_type": The detected category.
            2. "json_ld": The strictly valid Schema.org JSON-LD object (minified).
            """
            
            response_schema = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": schema_prompt},
                    {"role": "user", "content": f"URL: {url}\n\nContent Sample:\n{content[:6000]}"} 
                ],
                response_format={"type": "json_object"}
            )
            
            schema_data = json.loads(response_schema.choices[0].message.content)
            schema_type = schema_data.get("schema_type", "WebSite")
            json_ld_obj = schema_data.get("json_ld", {})

            # --- Step 2: RAG-Optimized llms.txt & Comprehensive Analysis ---
            
            custom_instruction_text = ""
            if custom_instruction:
                custom_instruction_text = f"\n\nUSER CUSTOM INSTRUCTION (Must be prioritized): {custom_instruction}"

            llm_txt_prompt = f"""
            You are an AI Optimization (AIO) specialist. Analyze the content deeply.
            
            IMPORTANT: Output all analysis, descriptions, and summaries in **{language}**.
            {custom_instruction_text}

            1. Write a 'llms.txt' summary optimized for RAG retrieval.
               - Start with a high-level overview.
               - Use bullet points for key services/features.
               - MANDATORY: Add a section "## Key Questions this Website Answers" at the bottom.
            2. Write specific 'seo_description' for search engines.
            3. Analyze for AIO Report (JSON):
               - "scores": {{ "usability": 0-100, "seo": 0-100, "content_quality": 0-100, "total": 0-100 }}
               - "summary_keywords": ["keyword1", "keyword2", ...] (Top 5 entities)
               - "pros": ["Good point 1", "Good point 2", ...]
               - "cons": ["Improvement 1", "Improvement 2", ...]
               - "recommendations": ["Actionable tip 1", "Actionable tip 2", ...]
                - "ghostlink_impact": [
                    {{ "title": "Search Visibility", "description": "Expected improvement...", "improvement": "+40%" }},
                    {{ "title": "AI Readability", "description": "How LLMs will better understand...", "improvement": "+85%" }}
                 ] (Generate 2-3 specific technical benefits of using GhostLink's JSON-LD & llms.txt)

            Return JSON: {{
                "llms_txt": "...", 
                "seo_description": "...", 
                "analysis": {{ 
                    "scores": {{...}}, 
                    "summary_keywords": [...], 
                    "pros": [...], 
                    "cons": [...], 
                    "recommendations": [...],
                    "ghostlink_impact": [...]
                }} 
            }}
            """

            response_meta = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": llm_txt_prompt},
                    {"role": "user", "content": content[:8000]} # Increased context limit slightly
                ],
                response_format={"type": "json_object"}
            )
            
            meta_data = json.loads(response_meta.choices[0].message.content)
            analysis_data = meta_data.get("analysis", {})
            total_score = analysis_data.get("scores", {}).get("total", 50)
            
            return {
                "schema_type": schema_type,
                "json_ld": json.dumps(json_ld_obj),
                "llms_txt": meta_data.get("llms_txt", ""),
                "seo_description": meta_data.get("seo_description", ""),
                "ai_score": total_score,
                "ai_analysis_json": json.dumps(analysis_data)
            }

        except Exception as e:
            logger.error(f"Error in generate_assets: {e}")
            return self._get_error_response(str(e))

    def _get_mock_response(self, url: str):
        return {
            "schema_type": "Corporate (Mock)",
            "json_ld": json.dumps({
                "@context": "https://schema.org",
                "@type": "Organization",
                "url": url,
                "name": "Mock Inc.",
                "description": "Mocked response due to missing API Key."
            }, indent=2),
            "llms_txt": f"# Mock Summary for {url}\n\nThis is a mock RAG summary.\n\n## Key Questions this Website Answers\n- What is this service?\n- How much does it cost?",
            "seo_description": "Mock SEO Description",
            "ai_score": 88,
            "ai_analysis_json": json.dumps({
                "scores": {"usability": 85, "seo": 90, "content_quality": 88, "total": 88},
                "summary_keywords": ["Mock", "Test", "AI"],
                "pros": ["Fast response", "Clear structure"],
                "cons": ["No real data", "Mock mode"],
                "recommendations": ["Connect OpenAI API", "Run real scan"],
                "ghostlink_impact": [
                    {"title": "Search Visibility", "description": "Enhanced rich snippets with valid JSON-LD.", "improvement": "+35%"},
                    {"title": "AI Agent Access", "description": "Optimized RAG retrieval via llms.txt standard.", "improvement": "+90%"}
                ]
            })
        }

    def _get_error_response(self, error_msg: str):
        return {
            "schema_type": "Error",
            "json_ld": "{}",
            "llms_txt": f"Error: {error_msg}",
            "seo_description": "Error failed analysis.",
            "ai_score": 0,
            "error_msg": error_msg # Return explicit error
        }

ai_service = AIService()
