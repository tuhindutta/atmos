"""General-purpose LangGraph ReAct agent with optional persistent-shell access."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from agents.atmos_resource_tools import create_atmos_resource_tools
from shell.persistent_shell_manager_tools import (
    create_persistent_shell_manager_tools,
)
from agents.sub_agent import sub_agent


ATMOS_DIRECTORY = Path(__file__).resolve().parent.parent / ".atmos"


def create_master_agent(
    model: str | BaseChatModel,
    *,
    python_runtime: str = "./.venv/bin/python",
    port: int = 8082,
    startup_timeout: float = 10.0,
    memory_tools: Sequence[BaseTool] = (),
    shell_tools: Sequence[BaseTool] | None = None,
    additional_tools: Sequence[BaseTool] = (),
):
    """Create Atmos with shell and user-provided resource tools."""
    for directory in (
        ATMOS_DIRECTORY / "skills",
        ATMOS_DIRECTORY / "agents",
        ATMOS_DIRECTORY / "playground",
    ):
        directory.mkdir(parents=True, exist_ok=True)

    path: str = f"./master_agent_{port}api.py"

    if shell_tools is None:
        shell_tools = create_persistent_shell_manager_tools(
            python_runtime=python_runtime,
            port=port,
            path=path,
            startup_timeout=startup_timeout,
        )
    resource_tools = create_atmos_resource_tools(ATMOS_DIRECTORY)

    with open("prompts/master_agent_prompt.md", "r") as f:
        system_prompt = f.read()

    return create_agent(
        model=model,
        tools=[
            *shell_tools,
            *resource_tools,
            sub_agent(model),
            *memory_tools,
            *additional_tools,
        ],
        name="Atmos",
        system_prompt=system_prompt,
    )


create_shell_react_agent = create_master_agent

__all__ = ["create_master_agent", "create_shell_react_agent"]
