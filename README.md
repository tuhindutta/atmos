# Atmos

Atmos is a locally run AI assistant with a browser-based chat interface. It can
use a persistent local shell, read and create agent/skill resources, keep
threaded conversation history and long-term memories in SQLite, and delegate
focused work to a child agent.

## Architecture and code references

- [**Agent architecture**](https://tuhindutta.github.io/atmos/documents/agent-architecture.html)
- [**Memory architecture**](https://tuhindutta.github.io/atmos/documents/memory-architecture.html)
- [**Tools architecture**](https://tuhindutta.github.io/atmos/documents/tools-architecture.html)
- [**Directory and module reference**](https://tuhindutta.github.io/atmos/documents/module-reference.html)
- [**GitHub**](https://github.com/tuhindutta/atmos/tree/main)

## Requirements

- Python 3.10 or newer
- Bash and a POSIX-compatible environment (the persistent shell uses a
  pseudo-terminal)
- An OpenAI API key

## Setup

Create and activate a virtual environment, then install the project
dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Set the API key in the environment or in a project-root `.env` file:

```dotenv
OPENAI_API_KEY=your_api_key
# Optional; defaults to gpt-6-luna in the web app.
OPENAI_MODEL=gpt-6-luna
```

Keep `.env` private; do not commit API keys.

## Run the web app

```bash
source .venv/bin/activate
python atmos.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). To use another port:

```bash
python atmos.py --port 8080
```

The app binds to loopback by default. **Do not expose it to untrusted networks:**
the agent can execute commands in a local shell.

## Features

- **Chat and threads:** Conversations are isolated by thread ID. The browser
  saves the active thread locally and can search or clear conversation history.
- **Persistent shell:** The agent can start a local shell API and use command,
  polling, input, and reset tools. The managed terminal is stopped during app
  shutdown.
- **Memory:** Short-term messages and agent event traces are stored in SQLite
  at `.atmos/agent_memory.sqlite3`. Long-term memories are shared across
  threads and can be saved, searched, or removed in the UI or with agent tools.
- **Resources:** The agent can list, read, and create supported skill and
  agent Markdown resources under `.atmos/`.
- **Delegation and progress:** The master agent can run focused work through a
  child agent and emit progress updates in the chat stream.
- **Activity trace:** Tool and agent activity is streamed to the browser and
  stored with completed assistant turns. The agent can retrieve prior traces
  with its conversation-history tool when needed.

## HTTP API

The browser UI uses these main endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Check whether the app is responsive |
| `GET` | `/api/threads` | List threads or search conversation text |
| `GET` | `/api/threads/{thread_id}/messages` | Read messages and recorded events |
| `POST` | `/api/chat` | Send a message and receive server-sent events |
| `DELETE` | `/api/threads/{thread_id}` | Clear a thread's conversation history |
| `GET` | `/api/memories` | List or search long-term memories |
| `POST` | `/api/memories` | Save a long-term memory |
| `DELETE` | `/api/memories/{memory_id}` | Delete a long-term memory |

`POST /api/chat` accepts JSON in the form:

```json
{
  "thread_id": "your-thread-id",
  "message": "Your request"
}
```

## Project layout

```text
.
├── atmos.py                 # FastAPI app, chat streaming, and runtime setup
├── agents/                  # Master/child agents, SQLite memory, tool factories
├── shell/                   # Persistent shell implementation, API template, tools
├── web/                     # Browser interface (HTML, CSS, JavaScript)
├── prompts/                 # Agent prompt and execution/delegation/memory protocols
├── documents/               # Architecture diagrams and module reference
├── .atmos/                  # Runtime SQLite database, MCP servers/registry, and user resources
├── requirements.txt
└── LICENSE
```

The shell API template is written to a generated Python file when the shell
starts. `.venv/`, `.env`, the SQLite database, and generated/runtime files are
local artifacts.

