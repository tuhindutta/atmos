"""General-purpose LangGraph ReAct agent with optional persistent-shell access."""

from __future__ import annotations

import sys
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool, tool

from agents.atmos_resource_tools import create_atmos_resource_tools
from shell.persistent_shell_manager_tools import (
    create_persistent_shell_manager_tools,
)


# ATMOS_DIRECTORY = Path(__file__).resolve().parent / ".atmos"


def sub_agent(model: str | BaseChatModel) -> BaseTool:

    @tool
    async def query_sub_agent(
        sub_agent_name: str,
        system_prompt: str,
        query: str,
        *,
        python_runtime: str = "./.venv/bin/python",
        port: int = 8083,
        startup_timeout: float = 10.0,
    ):
        """Create Atmos with shell and user-provided resource tools."""

        # for directory in (
        #     ATMOS_DIRECTORY / "skills",
        #     ATMOS_DIRECTORY / "agents",
        #     ATMOS_DIRECTORY / "playground",
        # ):
        #     directory.mkdir(parents=True, exist_ok=True)

        path: str = f"./{sub_agent_name}_sub_agent_{port}api_shell.py"

        shell_tools = create_persistent_shell_manager_tools(
            python_runtime=python_runtime,
            port=port,
            path=path,
            startup_timeout=startup_timeout,
        )
        # resource_tools = create_atmos_resource_tools(ATMOS_DIRECTORY)

        agent = create_agent(
            model=model,
            tools=[*shell_tools],
            name="Atmos",
            system_prompt=system_prompt,
        )

        try:
            output = await agent.ainvoke(
                {"messages": [{"role": "user", "content": query}]}
            )
            return output["messages"][-1].content
        finally:
            stop_tool = next(
                (
                    shell_tool
                    for shell_tool in shell_tools
                    if shell_tool.name == "stop_persistent_terminal"
                ),
                None,
            )
            if stop_tool is not None:
                try:
                    stop_tool.invoke({})
                except Exception as exc:
                    print(
                        f"Failed to stop the child persistent terminal: {exc}",
                        file=sys.stderr,
                    )

    return query_sub_agent


# create_shell_react_agent = create_master_agent

# __all__ = ["create_master_agent", "create_shell_react_agent"]
