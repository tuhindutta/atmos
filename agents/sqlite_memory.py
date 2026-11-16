"""SQLite-backed short-term conversation history and long-term memories."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from langchain_core.tools import BaseTool, tool


class SQLiteMemory:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS conversation_messages_thread_id_id
                    ON conversation_messages(thread_id, id);

                CREATE TABLE IF NOT EXISTS conversation_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    assistant_message_id INTEGER NOT NULL
                        REFERENCES conversation_messages(id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS conversation_events_message_id
                    ON conversation_events(assistant_message_id, id);

                CREATE TABLE IF NOT EXISTS long_term_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def recent_messages(
        self, thread_id: str, *, limit: int = 20
    ) -> list[dict[str, str]]:
        if not thread_id.strip():
            raise ValueError("thread_id must not be empty")
        if limit < 1:
            raise ValueError("limit must be positive")

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT role, content
                FROM conversation_messages
                WHERE thread_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (thread_id, limit),
            ).fetchall()
        return [
            {"role": role, "content": content}
            for role, content in reversed(rows)
        ]

    def save_turn(
        self,
        thread_id: str,
        query: str,
        response: str,
        *,
        events: list[dict[str, Any]] | None = None,
    ) -> None:
        if not thread_id.strip():
            raise ValueError("thread_id must not be empty")

        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO conversation_messages (thread_id, role, content)
                VALUES (?, ?, ?)
                """,
                (thread_id, "user", query),
            )
            cursor = connection.execute(
                """
                INSERT INTO conversation_messages (thread_id, role, content)
                VALUES (?, ?, ?)
                """,
                (thread_id, "assistant", response),
            )
            assistant_message_id = cursor.lastrowid
            if events:
                connection.executemany(
                    """
                    INSERT INTO conversation_events
                        (assistant_message_id, event_type, payload)
                    VALUES (?, ?, ?)
                    """,
                    (
                        (
                            assistant_message_id,
                            event["type"],
                            json.dumps(event, ensure_ascii=False, default=str),
                        )
                        for event in events
                    ),
                )

    def recent_messages_with_events(
        self, thread_id: str, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        if not thread_id.strip():
            raise ValueError("thread_id must not be empty")
        if limit < 1:
            raise ValueError("limit must be positive")

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, role, content
                FROM conversation_messages
                WHERE thread_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (thread_id, limit),
            ).fetchall()
            message_ids = [row[0] for row in rows if row[1] == "assistant"]
            events_by_message: dict[int, list[dict[str, Any]]] = {}
            if message_ids:
                placeholders = ",".join("?" for _ in message_ids)
                event_rows = connection.execute(
                    f"""
                    SELECT assistant_message_id, payload
                    FROM conversation_events
                    WHERE assistant_message_id IN ({placeholders})
                    ORDER BY id
                    """,
                    message_ids,
                ).fetchall()
                for message_id, payload in event_rows:
                    events_by_message.setdefault(message_id, []).append(
                        json.loads(payload)
                    )

        return [
            {
                "role": role,
                "content": content,
                "events": events_by_message.get(message_id, []),
            }
            for message_id, role, content in reversed(rows)
        ]

    def list_threads(self) -> list[str]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT thread_id
                FROM conversation_messages
                GROUP BY thread_id
                ORDER BY MAX(id) DESC
                """
            ).fetchall()
        return [row[0] for row in rows]

    def search_conversations(
        self, query: str, *, limit: int = 100
    ) -> list[dict[str, str]]:
        query = query.strip()
        if not query:
            return []
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT thread_id, role, substr(content, 1, 300), created_at
                FROM conversation_messages
                WHERE instr(lower(content), lower(?)) > 0
                ORDER BY id DESC
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        return [
            {
                "thread_id": thread_id,
                "role": role,
                "content": content,
                "created_at": created_at,
            }
            for thread_id, role, content, created_at in rows
        ]

    def clear_thread(self, thread_id: str) -> int:
        if not thread_id.strip():
            raise ValueError("thread_id must not be empty")

        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM conversation_messages WHERE thread_id = ?",
                (thread_id,),
            )
        return cursor.rowcount

    def remember(self, content: str) -> str:
        content = content.strip()
        if not content:
            raise ValueError("Memory content must not be empty")

        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO long_term_memories (content)
                VALUES (?)
                ON CONFLICT(content) DO UPDATE SET
                    updated_at = CURRENT_TIMESTAMP
                """,
                (content,),
            )
        return "Saved the long-term memory."

    def list_memories(
        self, query: str = "", *, limit: int = 50
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, content, created_at, updated_at
                FROM long_term_memories
                ORDER BY updated_at DESC, id DESC
                """
            ).fetchall()

        terms = set(re.findall(r"\w{2,}", query.casefold()))
        ranked = [
            (
                sum(term in content.casefold() for term in terms),
                updated_at,
                memory_id,
                content,
                created_at,
            )
            for memory_id, content, created_at, updated_at in rows
        ]
        if terms:
            ranked = [item for item in ranked if item[0] > 0]
            ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)

        return [
            {
                "id": memory_id,
                "content": content,
                "created_at": created_at,
                "updated_at": updated_at,
            }
            for _, updated_at, memory_id, content, created_at in ranked[:limit]
        ]

    def delete_memory(self, memory_id: int) -> bool:
        if memory_id < 1:
            raise ValueError("memory_id must be positive")

        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM long_term_memories WHERE id = ?",
                (memory_id,),
            )
        return cursor.rowcount > 0

    def search(self, query: str, *, limit: int = 10) -> list[str]:
        return [
            memory["content"]
            for memory in self.list_memories(query, limit=limit)
        ]

    def create_tools(
        self, current_thread_id: Callable[[], str | None]
    ) -> list[BaseTool]:
        @tool
        def remember_memory(content: str) -> str:
            """Save a durable, non-sensitive fact or preference for future tasks."""
            return self.remember(content)

        @tool
        def search_memories(query: str = "", limit: int = 10) -> str:
            """Search saved long-term memories by keywords, or list recent memories."""
            memories = self.search(query, limit=limit)
            if not memories:
                return "No matching long-term memories found."
            return "\n".join(f"- {memory}" for memory in memories)

        @tool
        def recent_messages_with_events_tool(limit: int = 20) -> str:
            """Retrieve recent messages and recorded tool calls/results for this thread.

            Use when asked what was said or which tools/actions were performed
            earlier in this conversation. Consult the recorded events rather
            than guessing.
            """
            thread_id = current_thread_id()
            if thread_id is None:
                raise RuntimeError("No active conversation thread.")
            messages = self.recent_messages_with_events(thread_id, limit=limit)
            return json.dumps(messages, ensure_ascii=False)

        return [remember_memory, search_memories, recent_messages_with_events_tool]


__all__ = ["SQLiteMemory"]
