---
name: mcp
description: Create, update, inspect, and run Python MCP servers in this repository using FastMCP.
---

# MCP server skill

Use this skill when the user asks to create, change, inspect, or run an MCP
server for this repository.

## Repository registry and existing servers

1. Resolve the repository root and read `<repo-root>/.atmos/mcp.md` before planning
   any MCP work. This is mandatory on every use of this skill, including
   requests to update or run an existing server.
2. Treat `.atmos/mcp.md` as the index of servers and their client-facing details.
   Read the corresponding files under `<repo-root>/.atmos/mcp/` for any existing
   server relevant to the request. Reuse or extend an existing server when it
   already provides the requested capability; do not make a duplicate.
3. If `.atmos/mcp.md` is missing, inspect `.atmos/mcp/` first, then create the registry and
   record any servers already present. Preserve existing entries when updating
   the index.

## Creating a server

- Implement servers only with the Python `fastmcp` package. Keep each server
  in its own descriptive directory, for example
  `.atmos/mcp/<server-name>/server.py`; keep any directly related tests or
  non-secret configuration alongside it.
- Before creating files, check the existing registry, server directories,
  installed FastMCP version, and project dependencies. Ask for clarification
  when the requested server's purpose, tools, or required data sources are
  not sufficiently specified. Do not invent access to external services or
  credentials.
- Use the repository's `.venv` for every Python operation. Run Python as
  `.venv/bin/python` and package commands as `.venv/bin/python -m pip`.
  Never fall back to a system Python, another virtual environment, or a
  global package install. If `.venv` or FastMCP is unavailable, report that
  explicitly rather than using another interpreter.
- Follow the installed FastMCP version's API. Keep server startup explicit
  and reproducible, and include a `__main__` entry point when the server is
  intended to be launched as a script.
- Prefer Streamable HTTP when the user needs a network-style endpoint. Bind
  to `127.0.0.1` by default, select a port that does not conflict with
  existing entries or services, and document the MCP endpoint (normally
  `http://127.0.0.1:<port>/mcp`). Do not expose a server on all interfaces
  unless the user specifically requests it. Use stdio when requested or
  when it is the appropriate client integration; stdio servers do not have a
  listening port or HTTP endpoint.
- Keep secrets out of source, the registry, and committed configuration.
  Read required credentials from environment variables, document their names,
  and provide only safe placeholders in examples.

## Registering an external MCP server

Use this procedure when the user provides or asks to register an MCP server
that is not implemented in this repository.

1. Gather the following details before updating `.atmos/mcp.md`; ask focused
   clarification questions for any required value that is missing:
   - server name and purpose;
   - transport (`stdio`, Streamable HTTP, SSE, or another supported transport);
   - how to start or connect to it, including an exact command or URL;
   - bind host and port if the server is network-accessible;
   - authentication mode and required environment variable names;
   - available tools, resources, and prompts;
   - client configuration details, such as headers or arguments;
   - setup, startup, usage, and shutdown instructions;
   - a README or source link if one is supplied.
2. Do not invent missing endpoints, ports, credentials, capabilities, or
   authentication modes. Record unknown optional values as `N/A` and mark
   genuinely unresolved required values as `TBD`, but do not register a server
   until enough information is available to connect or start it.
3. Never store secret values in `.atmos/mcp.md`, source files, or committed
   configuration. Use environment variable names and safe placeholders only.
4. Reuse an existing entry when the external server is already registered.
   Update the entry instead of creating a duplicate. Add the entry under a
   clearly labeled external-server section in `.atmos/mcp.md`.
5. Preserve the registry format and include, for every external server:
   name, purpose, status, provider or source, implementation location or
   external status, transport, host and port where applicable, exact endpoint
   or start command, client configuration, capabilities, required environment
   variable names, setup notes, and the source or documentation link.

Use this entry shape:

```markdown
## <Server name>

- **Type:** External MCP
- **Purpose:** ...
- **Provider/source:** ...
- **Implementation:** External; documentation: <URL or N/A>
- **Transport:** ...
- **Host:** ...
- **Port:** ...
- **Endpoint or start command:** ...
- **Client configuration:** ...
- **Tools:** ...
- **Resources/prompts:** ...
- **Configuration:** Required environment variables: `VAR_NAME`; no secret values.
- **Setup/startup/shutdown:** ...
- **Status:** Registered
```

## Registry updates and usage documentation

After creating or changing a server, update `<repo-root>/.atmos/mcp.md` in the same
change. Preserve its index format and include, for every server:

- name, purpose, and implementation path;
- transport, bind host where applicable, port where applicable, and exact
  endpoint where applicable;
- exact command to start it from the repository root, using
  `.venv/bin/python`;
- how a client should connect or configure the server;
- available tools, resources, or prompts and their purpose;
- required environment variable names and any authentication/configuration
  notes, without secret values.

Document local setup, startup, shutdown, and a basic connection/use example
in `.atmos/mcp.md` or the server's own README, and link to that README from the
registry. Mark inapplicable transport details as `N/A`; do not guess an
endpoint, port, authentication mode, or server capability. Keep the root
index accurate if startup details or ports change.

## Verification

Use `.venv/bin/python` to check Python syntax and run relevant server tests.
When the server can be started safely, verify its documented startup and
connection details. Do not claim a server is working unless the checks
actually succeed.
