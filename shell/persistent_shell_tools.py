"""LangChain tools for the persistent-shell HTTP API."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from langchain_core.tools import BaseTool, tool


def _post(
    base_url: str,
    endpoint: str,
    payload: dict[str, Any],
    quiet_timeout: float,
) -> dict[str, Any]:
    request = Request(
        f"{base_url}/{endpoint}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=max(quiet_timeout + 5, 5)) as response:
            result = json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Persistent shell API returned HTTP {exc.code}: {detail}"
        ) from exc

    if not isinstance(result, dict):
        raise RuntimeError("Persistent shell API returned an invalid response")
    return result


def create_shell_tools(base_url: str | Callable[[], str]) -> list[BaseTool]:
    """Create shell tools bound to the given API base URL."""
    def get_api_url() -> str:
        api_url = base_url if isinstance(base_url, str) else base_url()
        if not api_url:
            raise RuntimeError("Start the persistent terminal before using shell tools")
        return api_url.rstrip("/")

    @tool
    def run_command(command: str, timeout: float = 1.0) -> dict[str, Any]:
        """Run a command in the persistent shell.

        Timeout is a quiet-period limit. If the result state is ``idle`` or
        ``waiting_for_input``, use ``poll_command`` or ``send_command_input``.
        """
        return _post(
            get_api_url(), "run", {"command": command, "timeout": timeout}, timeout
        )

    @tool
    def poll_command(timeout: float = 1.0) -> dict[str, Any]:
        """Wait for output from the currently active shell command."""
        return _post(get_api_url(), "poll", {"timeout": timeout}, timeout)

    @tool
    def send_command_input(
        text: str, newline: bool = True, timeout: float = 1.0
    ) -> dict[str, Any]:
        """Send input to a command waiting for terminal input."""
        return _post(
            get_api_url(),
            "send_input",
            {"text": text, "newline": newline, "timeout": timeout},
            timeout,
        )

    @tool
    def reset_shell() -> dict[str, Any]:
        """Terminate the active command and reset the persistent shell session."""
        return _post(get_api_url(), "reset", {}, 0)

    return [run_command, poll_command, send_command_input, reset_shell]


__all__ = ["create_shell_tools"]
