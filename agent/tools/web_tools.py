import urllib.request
import urllib.error
import re
from .base import BaseTool

try:
    from duckduckgo_search import DDGS
except ImportError:
    DDGS = None


class FetchUrlTool(BaseTool):
    name = "fetch_url"
    description = (
        "Fetch the content of a URL and return the text. "
        "Useful for reading documentation, APIs, or web pages."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to fetch."},
            "max_chars": {"type": "integer", "description": "Max characters to return. Default: 8000."},
        },
        "required": ["url"],
    }

    def execute(self, url: str, max_chars: int = 8000) -> str:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 ApexForge-Swarm/1.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                charset = "utf-8"
                ct = resp.headers.get_content_charset()
                if ct:
                    charset = ct
                text = raw.decode(charset, errors="replace")

            # Strip HTML tags if it looks like HTML
            if "<html" in text[:500].lower() or "<!doctype" in text[:100].lower():
                text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"\s{3,}", "\n\n", text)
                text = text.strip()

            if len(text) > max_chars:
                text = text[:max_chars] + f"\n\n[... truncated at {max_chars} chars]"
            return text
        except urllib.error.HTTPError as e:
            return f"HTTP Error {e.code}: {e.reason}"
        except urllib.error.URLError as e:
            return f"URL Error: {e.reason}"
        except Exception as e:
            return f"Error fetching URL: {e}"


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Search the web using DuckDuckGo. "
        "Returns a list of relevant snippets and URLs. "
        "Useful for answering questions about current events or finding documentation."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
            "max_results": {"type": "integer", "description": "Max results to return. Default: 5."},
        },
        "required": ["query"],
    }

    def execute(self, query: str, max_results: int = 5) -> str:
        if not DDGS:
            return "Error: duckduckgo_search library not installed."
        try:
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append(f"Title: {r['title']}\nURL: {r['href']}\nSnippet: {r['body']}\n")

            if not results:
                return "No results found."

            return "\n---\n".join(results)
        except Exception as e:
            return f"Search error: {e}"
