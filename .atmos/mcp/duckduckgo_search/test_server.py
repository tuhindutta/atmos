"""Offline tests for the DuckDuckGo Search MCP tool."""

import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

_server_path = Path(__file__).with_name("server.py")
_spec = importlib.util.spec_from_file_location("duckduckgo_search_server", _server_path)
server = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(server)


class DuckDuckGoSearchTests(unittest.TestCase):
    def test_validates_query_and_limit(self):
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            server.duckduckgo_search(" ")
        with self.assertRaisesRegex(ValueError, "4000 characters"):
            server.duckduckgo_search("x" * 4001)
        for invalid in (0, 11, "5", True):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "integer from 1 to 10"):
                server.duckduckgo_search("hello", invalid)

    def test_parses_and_limits_results(self):
        html = b'''<table>
          <tr><td><a class="result-link" href="https://example.com/one">First <b>result</b></a></td></tr>
          <tr><td class="result-snippet">A short snippet.</td></tr>
          <tr><td><a class="result-link" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Ftwo">Second</a></td></tr>
          <tr><td class="result-snippet">Another snippet</td></tr>
        </table>'''
        with patch.object(server, "urlopen", return_value=io.BytesIO(html)) as mocked:
            result = server.duckduckgo_search(" cyclone akvan ", num_results=1)

        self.assertEqual(result["query"], "cyclone akvan")
        self.assertEqual(result["results"], [{
            "title": "First result",
            "url": "https://example.com/one",
            "snippet": "A short snippet.",
        }])
        request = mocked.call_args.args[0]
        self.assertIn("q=cyclone+akvan", request.full_url)
        self.assertEqual(request.get_header("User-agent"), "Mozilla/5.0 (compatible; Atmos-DuckDuckGo-Search/1.0)")

    def test_extracts_redirect_url(self):
        html = '<a class="result-link" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fitem">Example</a>'
        self.assertEqual(server._extract_results(html, 5)[0]["url"], "https://example.org/item")

    def test_network_error_is_reported(self):
        from urllib.error import URLError
        with patch.object(server, "urlopen", side_effect=URLError("offline")):
            with self.assertRaisesRegex(RuntimeError, "Could not reach DuckDuckGo"):
                server.duckduckgo_search("hello")


if __name__ == "__main__":
    unittest.main()
