"""Tools for discovering and reading Atmos skill and agent definitions."""

from __future__ import annotations

from itertools import islice
from pathlib import Path
from typing import Literal

from langchain_core.tools import BaseTool, tool


def create_atmos_resource_tools(atmos_directory: str | Path) -> list[BaseTool]:
    """Create tools for reading and creating user-provided files under ``.atmos``."""
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

    @tool
    def create_atmos_resource(
        resource_type: Literal["skills", "agents"],
        path: str,
        content: str,
    ) -> dict[str, str]:
        """Create a skill or agent resource under .atmos.

        ``path`` is relative to the resource type. Skills must use
        ``<name>/SKILL.md`` and agents must use ``<name>.md``.
        Existing files are never overwritten.
        """
        relative = Path(path)
        parts = relative.parts
        valid_skill = (
            resource_type == "skills"
            and len(parts) == 2
            and parts[0] not in ("", ".", "..")
            and parts[1] == "SKILL.md"
        )
        valid_agent = (
            resource_type == "agents"
            and len(parts) == 1
            and parts[0].endswith(".md")
            and parts[0] not in (".", "..")
        )
        if relative.is_absolute() or ".." in parts or not (valid_skill or valid_agent):
            raise ValueError(
                "Skills require <name>/SKILL.md and agents require <name>.md"
            )

        target = (root / resource_type / relative).resolve()
        if root not in target.parents:
            raise ValueError("Resource path must stay inside the .atmos directory")

        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as resource:
            resource.write(content)
        return {
            "path": target.relative_to(root).as_posix(),
            "status": "created",
        }

    return [list_atmos_resources, read_atmos_resource, create_atmos_resource]


__all__ = ["create_atmos_resource_tools"]
