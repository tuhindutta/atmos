"""Tools for discovering and reading Atmos skill and agent definitions."""

from __future__ import annotations

from itertools import islice
from pathlib import Path
from typing import Literal

from langchain_core.tools import BaseTool, tool


def create_atmos_resource_tools(atmos_directory: str | Path) -> list[BaseTool]:
    """Create tools for reading user-provided files under ``.atmos``."""
    root = Path(atmos_directory).expanduser().resolve()

    @tool
    def list_atmos_resources(
        category: Literal["all", "skills", "agents"] = "all",
    ) -> dict[str, list[str]]:
        """List available skill and agent Markdown files under .atmos."""
        resources: dict[str, list[str]] = {"skills": [], "agents": []}
        if category in ("all", "skills"):
            resources["skills"] = sorted(
                path.relative_to(root).as_posix()
                for path in (root / "skills").glob("*/SKILL.md")
                if path.is_file()
            )
        if category in ("all", "agents"):
            resources["agents"] = sorted(
                path.relative_to(root).as_posix()
                for path in (root / "agents").glob("*.md")
                if path.is_file()
            )
        return resources

    @tool
    def read_atmos_resource(
        relative_path: str,
        start_line: int = 1,
        max_lines: int = 200,
    ) -> dict[str, str | int | bool | None]:
        """Read a skill or agent definition, optionally in line-based chunks.

        Only ``skills/<name>/SKILL.md`` and ``agents/<name>.md`` are readable.
        Use ``next_start_line`` to continue when ``has_more`` is true.
        """
        if start_line < 1:
            raise ValueError("start_line must be at least 1")
        if not 1 <= max_lines <= 1000:
            raise ValueError("max_lines must be between 1 and 1000")

        relative = Path(relative_path)
        parts = relative.parts
        valid_skill = (
            len(parts) == 3 and parts[0] == "skills" and parts[2] == "SKILL.md"
        )
        valid_agent = (
            len(parts) == 2 and parts[0] == "agents" and parts[1].endswith(".md")
        )
        if relative.is_absolute() or ".." in parts or not (valid_skill or valid_agent):
            raise ValueError(
                "Only skills/<name>/SKILL.md and agents/<name>.md files are allowed"
            )

        target = (root / relative).resolve()
        if root not in target.parents:
            raise ValueError("Resource path must stay inside the .atmos directory")
        if not target.is_file():
            raise FileNotFoundError(f"Atmos resource not found: {relative_path}")

        with target.open(encoding="utf-8") as resource:
            chunk = list(
                islice(resource, start_line - 1, start_line - 1 + max_lines + 1)
            )
        has_more = len(chunk) > max_lines
        content = "".join(chunk[:max_lines])
        return {
            "path": relative.as_posix(),
            "start_line": start_line,
            "content": content,
            "has_more": has_more,
            "next_start_line": start_line + max_lines if has_more else None,
        }

    return [list_atmos_resources, read_atmos_resource]


__all__ = ["create_atmos_resource_tools"]
