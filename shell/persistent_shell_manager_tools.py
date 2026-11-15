"""LangChain tools to start, use, and stop a persistent-shell API."""

from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass
from subprocess import Popen, TimeoutExpired
from threading import Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from langchain_core.tools import BaseTool, tool

from shell.create_shell_persistent_fastapi_script import Shell
from shell.persistent_shell_tools import create_shell_tools

PORT_ATTEMPTS = 5


@dataclass
class _ActiveShell:
    shell: Shell
    process: Popen[bytes]
    port: int


def _is_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        try:
            server_socket.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _is_healthy(base_url: str) -> bool:
    try:
        with urlopen(f"{base_url}/health", timeout=1) as response:
            body = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return False
    return isinstance(body, dict) and body.get("status") == "ok"


def _terminate_process(process: Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except TimeoutExpired:
        process.kill()
        process.wait()


def create_persistent_shell_manager_tools(
    python_runtime: str = "./.venv/bin/python",
    port: int = 8082,
    path: str = "./shell_api.py",
    startup_timeout: float = 10.0,
) -> list[BaseTool]:
    """Create tools to manage and use a local persistent terminal.

    Starting tries the requested port and up to four successive ports. Shell
    command tools use whichever endpoint successfully starts.
    """
    if startup_timeout <= 0:
        raise ValueError("startup_timeout must be positive")
    if not 1 <= port <= 65535 - PORT_ATTEMPTS + 1:
        raise ValueError(f"port must be between 1 and {65535 - PORT_ATTEMPTS + 1}")

    active: _ActiveShell | None = None
    lock = Lock()

    def active_base_url() -> str:
        with lock:
            if active is None or active.process.poll() is not None:
                raise RuntimeError(
                    "Start the persistent terminal before using shell tools"
                )
            return f"http://127.0.0.1:{active.port}"

    shell_tools = create_shell_tools(active_base_url)

    @tool
    def start_persistent_terminal() -> dict[str, Any]:
        """Start the persistent terminal API, trying up to five consecutive ports."""
        nonlocal active
        with lock:
            if active is not None and active.process.poll() is None:
                base_url = f"http://127.0.0.1:{active.port}"
                if _is_healthy(base_url):
                    return {
                        "status": "already_running",
                        "base_url": base_url,
                        "port": active.port,
                        "shell_tools": [shell_tool.name for shell_tool in shell_tools],
                    }
                _terminate_process(active.process)
                active.shell.delete_shell_instance()
                active = None

            attempted_ports: list[int] = []
            failures: list[str] = []
            for candidate_port in range(port, port + PORT_ATTEMPTS):
                attempted_ports.append(candidate_port)
                if not _is_port_available(candidate_port):
                    failures.append(f"{candidate_port} is occupied")
                    continue

                shell = Shell(python_runtime, path, candidate_port)
                try:
                    shell.create_shell_instance()
                    process = shell.launch()
                except OSError as exc:
                    shell.delete_shell_instance()
                    return {
                        "status": "error",
                        "message": f"Could not launch the shell API: {exc}",
                        "attempted_ports": attempted_ports,
                    }

                deadline = time.monotonic() + startup_timeout
                while time.monotonic() < deadline:
                    exit_code = process.poll()
                    if exit_code is not None:
                        shell.delete_shell_instance()
                        failures.append(
                            f"{candidate_port} exited during startup with code {exit_code}"
                        )
                        break
                    base_url = f"http://127.0.0.1:{candidate_port}"
                    if _is_healthy(base_url):
                        active = _ActiveShell(
                            shell=shell, process=process, port=candidate_port
                        )
                        return {
                            "status": "started",
                            "base_url": base_url,
                            "port": candidate_port,
                            "shell_tools": [
                                shell_tool.name for shell_tool in shell_tools
                            ],
                            "attempted_ports": attempted_ports,
                        }
                    time.sleep(0.1)
                else:
                    _terminate_process(process)
                    shell.delete_shell_instance()
                    failures.append(
                        f"{candidate_port} did not become healthy within "
                        f"{startup_timeout:g} seconds"
                    )

            return {
                "status": "error",
                "message": (
                    f"Could not start the persistent shell after {PORT_ATTEMPTS} "
                    f"attempts on ports {port}-{port + PORT_ATTEMPTS - 1}: "
                    + "; ".join(failures)
                ),
                "attempted_ports": attempted_ports,
            }

    @tool
    def stop_persistent_terminal() -> dict[str, Any]:
        """Stop the managed API process and close its persistent shell."""
        nonlocal active
        with lock:
            if active is None:
                return {"status": "not_running"}
            port_to_stop = active.port
            _terminate_process(active.process)
            script_deleted = active.shell.delete_shell_instance()
            active = None
            return {
                "status": "stopped",
                "port": port_to_stop,
                "script_deleted": script_deleted,
            }

    return [start_persistent_terminal, *shell_tools, stop_persistent_terminal]


__all__ = ["create_persistent_shell_manager_tools"]
