# MCP servers

## DuckDuckGo Search

- **Purpose:** Free web search returning ordinary result titles, URLs, and snippets (not AI-generated summaries).
- **Implementation:** `.atmos/mcp/duckduckgo_search/server.py` (details: [server README](mcp/duckduckgo_search/README.md)).
- **Transport:** Streamable HTTP on `127.0.0.1:8083`; endpoint: `http://127.0.0.1:8083/mcp`.
- **Start command (from repository root):** `.venv/bin/python .atmos/mcp/duckduckgo_search/server.py`.
- **Client connection:** Configure an MCP client with URL `http://127.0.0.1:8083/mcp`; see the server README.
- **Tools:** `duckduckgo_search(query, num_results=5)` searches DuckDuckGo; `num_results` must be 1-10.
- **Resources/prompts:** None.
- **Configuration:** No credentials or API key required. Results come from DuckDuckGo's public Lite search page and remain subject to its policies and rate limits.
