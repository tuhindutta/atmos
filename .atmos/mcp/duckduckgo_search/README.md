# DuckDuckGo Search MCP server

This server exposes `duckduckgo_search(query, num_results=5)`. It uses
DuckDuckGo's public Lite search page and returns a list of ordinary web results
(titles, URLs, and snippets). It does not use Gemini or generate AI summaries,
and requires no API key or paid search API. Availability and usage are subject
to DuckDuckGo's service policies and rate limits.

## Configure and run

From the repository root:

```sh
.venv/bin/python .atmos/mcp/duckduckgo_search/server.py
```

The server uses Streamable HTTP, bound to loopback only:

- MCP endpoint: `http://127.0.0.1:8083/mcp`
- Bind host: `127.0.0.1`
- Stop with Ctrl-C in the server terminal.

Example MCP client configuration:

```json
{
  "mcpServers": {
    "duckduckgo-search": {
      "url": "http://127.0.0.1:8083/mcp"
    }
  }
}
```

## Tool use

Call `duckduckgo_search` with a query and optionally set `num_results` from 1
to 10. For example:

```text
duckduckgo_search(query="cyclone Akvan", num_results=3)
```

No credentials or API key are required.
