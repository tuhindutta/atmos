"""User-facing progress reporting for streamed agent interfaces."""

from __future__ import annotations

from langchain_core.callbacks import adispatch_custom_event
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool


@tool
async def report_progress(message: str, config: RunnableConfig) -> str:
    """Send a brief user-facing status update (not more than 500 characters), never private reasoning."""
    message = message.strip()
    if not message:
        raise ValueError("Progress message must not be empty.")
    if len(message) > 500:
        raise ValueError("Progress message must not exceed 240 characters.")

    await adispatch_custom_event(
        "agent_progress",
        {"message": message},
        config=config,
    )
    return "Progress update sent."


def create_progress_tools() -> list[BaseTool]:
    return [report_progress]


__all__ = ["create_progress_tools"]
