"""Loopback-only browser interface for the Atmos master agent."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from contextvars import ContextVar
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import uvicorn
import bleach
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_openai import ChatOpenAI
from markdown_it import MarkdownIt
from pydantic import BaseModel, Field

from agents.master_agent import create_master_agent
from agents.progress_tools import create_progress_tools
from agents.sqlite_memory import SQLiteMemory
from shell.persistent_shell_manager_tools import (
    create_persistent_shell_manager_tools,
)


PROJECT_ROOT = Path(__file__).resolve().parent
WEB_ROOT = PROJECT_ROOT / "web"
DEFAULT_DATABASE = PROJECT_ROOT / ".atmos" / "agent_memory.sqlite3"
HISTORY_LIMIT = 20
MAX_ERROR_RECOVERIES = 2
logger = logging.getLogger(__name__)

load_dotenv(PROJECT_ROOT / ".env")

MARKDOWN = MarkdownIt("commonmark", {"html": False, "breaks": True}).enable(
    ["table", "strikethrough"]
)
MARKDOWN_TAGS = set(bleach.sanitizer.ALLOWED_TAGS) | {
    "blockquote",
    "br",
    "code",
    "del",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}
MARKDOWN_ATTRIBUTES = {
    "a": ["href", "title"],
    "code": ["class"],
    "td": ["align"],
    "th": ["align"],
}

@dataclass
class AgentRuntime:
    agent: Any
    memory: SQLiteMemory
    shell_tools: list[Any]
    request_lock: asyncio.Lock


class ChatRequest(BaseModel):
    thread_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=20_000)


class MemoryRequest(BaseModel):
    content: str = Field(min_length=1, max_length=5_000)


def render_markdown(source: str) -> str:
    rendered = MARKDOWN.render(source)
    return bleach.clean(
        rendered,
        tags=MARKDOWN_TAGS,
        attributes=MARKDOWN_ATTRIBUTES,
        strip=True,
    )


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return "" if content is None else str(content)


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        return json_safe(value.model_dump())
    if hasattr(value, "content"):
        return {
            "type": getattr(value, "type", type(value).__name__),
            "content": json_safe(value.content),
            "tool_calls": json_safe(getattr(value, "tool_calls", [])),
        }
    return str(value)


def message_output(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        content = value.get("content", "")
        tool_calls = value.get("tool_calls", [])
    else:
        content = getattr(value, "content", "")
        tool_calls = getattr(value, "tool_calls", [])
    return {
        "content": content_text(content),
        "raw_content": json_safe(content),
        "tool_calls": json_safe(tool_calls),
    }


def final_message(output: Any) -> dict[str, Any] | None:
    messages = output.get("messages") if isinstance(output, dict) else None
    if not isinstance(messages, (list, tuple)):
        messages = [output]
    for message in reversed(messages):
        message_type = (
            message.get("type") or message.get("role")
            if isinstance(message, dict)
            else getattr(message, "type", "")
        )
        if message_type in {"ai", "assistant"}:
            return message_output(message)
    return None


async def stream_agent_events(
    agent: Any,
    query: str,
    prior_messages: list[dict[str, str]],
):
    messages = [*prior_messages, {"role": "user", "content": query}]
    for recovery in range(MAX_ERROR_RECOVERIES + 1):
        answer = ""
        try:
            async for event in agent.astream_events(
                {"messages": messages},
                version="v2",
                config={"recursion_limit": 50},
            ):
                event_name = event.get("event")
                data = event.get("data") or {}
                run_id = str(event.get("run_id", ""))
                if event_name == "on_chat_model_start":
                    yield {
                        "type": "ai_start",
                        "run_id": run_id,
                        "name": event.get("name", "AI"),
                    }
                elif event_name == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    content = content_text(
                        chunk.get("content", "")
                        if isinstance(chunk, dict)
                        else getattr(chunk, "content", "")
                    )
                    if content:
                        yield {
                            "type": "ai_delta",
                            "run_id": run_id,
                            "content": content,
                        }
                elif event_name == "on_chat_model_end":
                    result = message_output(data.get("output"))
                    result["html"] = render_markdown(result["content"])
                    if result["content"]:
                        answer = result["content"]
                    yield {
                        "type": "ai_message",
                        "run_id": run_id,
                        "name": event.get("name", "AI"),
                        **result,
                    }
                elif event_name == "on_tool_start":
                    yield {
                        "type": "tool_start",
                        "run_id": run_id,
                        "name": event.get("name", "tool"),
                        "input": json_safe(data.get("input")),
                    }
                elif event_name == "on_tool_end":
                    yield {
                        "type": "tool_end",
                        "run_id": run_id,
                        "name": event.get("name", "tool"),
                        "output": json_safe(data.get("output")),
                    }
                elif event_name == "on_tool_error":
                    yield {
                        "type": "tool_error",
                        "run_id": run_id,
                        "name": event.get("name", "tool"),
                        "error": str(data.get("error", "Tool failed.")),
                    }
                elif event_name == "on_custom_event":
                    if event.get("name") == "agent_progress":
                        message = data.get("message")
                        if isinstance(message, str):
                            yield {"type": "progress", "message": message}
                    else:
                        yield {
                            "type": "custom",
                            "name": event.get("name", "Agent event"),
                            "data": json_safe(data),
                        }
                elif event_name == "on_chain_end" and not event.get("parent_ids"):
                    result = final_message(data.get("output"))
                    if result and result["content"]:
                        answer = result["content"]
            yield {"type": "final", "answer": answer}
            return
        except Exception as exc:
            if recovery == MAX_ERROR_RECOVERIES:
                raise
            logger.warning(
                "Agent execution failed; retrying (%d/%d): %s",
                recovery + 1,
                MAX_ERROR_RECOVERIES,
                exc,
            )
            yield {
                "type": "retry",
                "message": f"{type(exc).__name__}: {exc}",
                "attempt": recovery + 1,
                "maximum": MAX_ERROR_RECOVERIES,
            }
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "The previous execution raised an error before completing. "
                        f"Error: {type(exc).__name__}: {exc}\n"
                        "Please diagnose what went wrong, adjust your approach, "
                        "and continue the original task."
                    ),
                }
            )
    raise RuntimeError("Agent exhausted its error recovery attempts")


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.chdir(PROJECT_ROOT)
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "Set OPENAI_API_KEY in the environment or project .env file."
        )

    memory = SQLiteMemory(app.state.database_path)
    shell_tools = create_persistent_shell_manager_tools(
        python_runtime="./.venv/bin/python",
        port=8082,
        path="./master_agent_8082api.py",
    )
    try:
        model = ChatOpenAI(model=os.environ.get("OPENAI_MODEL", "gpt-6-luna"))
        app.state.runtime = AgentRuntime(
            agent=create_master_agent(
                model,
                memory_tools=memory.create_tools(app.state.current_thread_id.get),
                shell_tools=shell_tools,
                additional_tools=create_progress_tools(),
            ),
            memory=memory,
            shell_tools=shell_tools,
            request_lock=asyncio.Lock(),
        )
        yield
    finally:
        stop_tool = next(
            (tool for tool in shell_tools if tool.name == "stop_persistent_terminal"),
            None,
        )
        if stop_tool is not None:
            try:
                stop_tool.invoke({})
            except Exception:
                logger.exception("Failed to stop the persistent terminal")


def create_app(database_path: Path = DEFAULT_DATABASE) -> FastAPI:
    app = FastAPI(
        title="Atmos Agent",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.database_path = database_path
    app.state.current_thread_id = ContextVar("current_thread_id", default=None)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost"],
    )

    @app.middleware("http")
    async def enforce_same_origin(request: Request, call_next):
        if request.method in {"POST", "DELETE"} and request.url.path.startswith(
            "/api/"
        ):
            origin = request.headers.get("origin")
            host = request.headers.get("host", "")
            if origin:
                parsed_origin = urlsplit(origin)
                expected_origin = f"{request.url.scheme}://{host}"
                if (
                    parsed_origin.scheme not in {"http", "https"}
                    or parsed_origin.netloc != host
                    or origin != expected_origin
                ):
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Cross-origin requests are not allowed."},
                    )
        return await call_next(request)

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(WEB_ROOT / "index.html")

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/threads")
    async def list_threads(
        request: Request,
        query: str = Query(default="", max_length=200),
    ) -> dict[str, Any]:
        memory = request.app.state.runtime.memory
        matches = memory.search_conversations(query) if query.strip() else []
        threads = (
            list(dict.fromkeys(match["thread_id"] for match in matches))
            if query.strip()
            else memory.list_threads()
        )
        return {"threads": threads, "matches": matches}

    @app.get("/api/threads/{thread_id}/messages")
    async def get_messages(
        thread_id: str,
        request: Request,
        limit: int = Query(default=200, ge=1, le=500),
    ) -> dict[str, Any]:
        validate_thread_id(thread_id)
        messages = request.app.state.runtime.memory.recent_messages_with_events(
            thread_id, limit=limit
        )
        for message in messages:
            if message["role"] == "assistant":
                message["html"] = render_markdown(message["content"])
        return {"thread_id": thread_id, "messages": messages}

    @app.post("/api/chat")
    async def chat(payload: ChatRequest, request: Request) -> StreamingResponse:
        thread_id = validate_thread_id(payload.thread_id)
        message = payload.message.strip()
        if not message:
            raise HTTPException(status_code=422, detail="Message cannot be empty.")

        runtime: AgentRuntime = request.app.state.runtime

        async def event_stream():
            trace: list[dict[str, Any]] = []
            async with runtime.request_lock:
                thread_id_token = request.app.state.current_thread_id.set(thread_id)
                try:
                    history = runtime.memory.recent_messages(
                        thread_id, limit=HISTORY_LIMIT
                    )
                    try:
                        async for event in stream_agent_events(
                            runtime.agent,
                            message,
                            history,
                        ):
                            if event["type"] == "final":
                                event["html"] = render_markdown(event["answer"])
                                runtime.memory.save_turn(
                                    thread_id,
                                    message,
                                    event["answer"],
                                    events=trace,
                                )
                                event["thread_id"] = thread_id
                            elif event["type"] != "ai_delta":
                                trace.append(event)
                            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    except Exception:
                        logger.exception("Agent request failed")
                        error = {
                            "type": "error",
                            "message": (
                                "The agent could not complete the request. "
                                "Check server logs."
                            )
                        }
                        yield f"data: {json.dumps(error)}\n\n"
                finally:
                    request.app.state.current_thread_id.reset(thread_id_token)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.delete("/api/threads/{thread_id}")
    async def clear_thread(thread_id: str, request: Request) -> dict[str, int]:
        validate_thread_id(thread_id)
        count = request.app.state.runtime.memory.clear_thread(thread_id)
        return {"deleted_messages": count}

    @app.get("/api/memories")
    async def list_memories(
        request: Request,
        query: str = Query(default="", max_length=200),
        limit: int = Query(default=50, ge=1, le=50),
    ) -> dict[str, Any]:
        memories = request.app.state.runtime.memory.list_memories(
            query,
            limit=limit,
        )
        return {"memories": memories}

    @app.post("/api/memories")
    async def save_memory(
        payload: MemoryRequest,
        request: Request,
    ) -> dict[str, str]:
        content = payload.content.strip()
        if not content:
            raise HTTPException(status_code=422, detail="Memory cannot be empty.")
        return {"message": request.app.state.runtime.memory.remember(content)}

    @app.delete("/api/memories/{memory_id}")
    async def delete_memory(
        memory_id: int,
        request: Request,
    ) -> dict[str, bool]:
        if not request.app.state.runtime.memory.delete_memory(memory_id):
            raise HTTPException(status_code=404, detail="Memory not found.")
        return {"deleted": True}

    app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")
    return app


def validate_thread_id(thread_id: str) -> str:
    thread_id = thread_id.strip()
    if not thread_id or len(thread_id) > 100:
        raise HTTPException(
            status_code=422,
            detail="Thread ID must contain between 1 and 100 characters.",
        )
    return thread_id


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Atmos browser interface.")
    parser.add_argument("--port", type=int, default=8000, help="Local port (default: 8000)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    print(f"Atmos browser interface: http://127.0.0.1:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
