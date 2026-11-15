# Delegation Protocol

Atmos currently implements one programmatic delegation tool:
`query_sub_agent`. Use it for complex work that benefits from a focused,
independent result; do not delegate simple tasks.

## What the tool does

- `query_sub_agent` accepts a child `system_prompt` and a `query`. It also
  accepts optional `python_runtime`, `port`, and `startup_timeout` settings.
- Each call creates a child agent using the same model as the master. The child
  receives its own persistent-shell management tools and Atmos resource tools.
- The master awaits the child's result before continuing. Delegation therefore
  returns as part of the current task; it is not a background job.
- The child has no memory tools, no delegation tool, and no built-in persistent
  conversation history. It receives the task and context supplied to that
  invocation.
- The child result is returned to the master as the child's final message
  content. Review it, check important claims as needed, and integrate relevant
  findings into the response to the user.

## Delegation practice

- Give the child a bounded question or work item, relevant context, and a clear
  expected result. Do not assume it can see unstated details from the master
  conversation.
- Treat the child result as input to review, not as a replacement for the
  master's responsibility to answer the user.
- Remember that the child's shell is separate from the master's shell. Do not
  imply that shell state, files, or running processes are shared between them.

## Current limits

- There is no implemented agent registry, persistent named-agent manager,
  background task system, or swarm orchestration. A skill or agent Markdown
  file that describes creating agents or swarms is guidance only; it does not
  add those capabilities to the program.
- The current child implementation creates its own shell and uses the same
  configured Atmos resource directory as the master. It does not pass through
  the master's memory tools or conversation history.
