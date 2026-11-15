#!/usr/bin/env python3
"""Persistent interactive Bash session backed by a pseudo-terminal.

Example::

    from persistent_shell import PersistentShell

    with PersistentShell() as shell:
        result = shell.run("printf 'hello\\n'")
        print(result.output, result.exit_code)

        result = shell.run("read -r -p 'Value: ' value; printf '<%s>\\n' \"$value\"")
        if result.state == "waiting_for_input":
            result = shell.send_input("sample")
        print(result.output, result.exit_code)

States are ``completed`` (exit code is known), ``waiting_for_input`` (a
recognized prompt was seen), and ``idle`` (no output arrived before the
poll interval; the command may still be working or waiting silently).
"""

from __future__ import annotations

import errno
import os
import pty
import re
import select
import shlex
import signal
import time
import uuid
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CommandResult:
    """Result of running, polling, or providing input to a command.

    Attributes:
        output: Newly collected terminal output, with ANSI escapes and terminal
            line endings normalized.
        state: ``completed``, ``waiting_for_input``, or ``idle``.
        exit_code: Command exit status when ``state`` is ``completed``;
            otherwise ``None``.
    """

    output: str
    state: str
    exit_code: Optional[int] = None


class ShellSessionError(RuntimeError):
    """Base exception for errors raised by a persistent shell session."""


class ShellSessionClosed(ShellSessionError):
    """Raised when an operation cannot proceed because the shell is closed."""


class PersistentShell:
    """Run commands in one interactive Bash process while retaining shell state.

    Quiet periods do not prove that a command needs input. The class reports
    ``waiting_for_input`` only when buffered output resembles a common prompt;
    otherwise it reports ``idle``. Input can be sent in either active state.
    This is a POSIX implementation because it relies on ``forkpty``.
    """

    _ANSI_ESCAPE = re.compile(
        r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1B\\))"
    )
    _PROMPT = re.compile(
        r"(?:password\s*:\s*|passphrase\s*:\s*|\[sudo[^\]]*\]\s*|"
        r"\[y/n\]\s*|\(y/n\)\s*|(?:continue|proceed)\?\s*|"
        r"(?:enter|input|value)\s*:\s*)$",
        re.IGNORECASE,
    )

    def __init__(self, shell: str = "bash", idle_timeout: float = 1.0,
                 encoding: str = "utf-8") -> None:
        """Start an interactive shell and configure command polling.

        Args:
            shell: Executable used to start the interactive shell.
            idle_timeout: Default quiet-period duration used by ``run``,
                ``poll``, and ``send_input`` when no timeout is supplied.
            encoding: Character encoding used for terminal input and output.

        Raises:
            ValueError: If ``idle_timeout`` is negative.
            OSError: If the pseudo-terminal or shell process cannot be started.
        """
        if idle_timeout < 0:
            raise ValueError("idle_timeout must be non-negative")
        self.shell = shell
        self.idle_timeout = idle_timeout
        self.encoding = encoding
        self._start_session()

    def _start_session(self) -> None:
        """Initialize Python-side state and launch a clean interactive shell."""
        self._active_marker: Optional[bytes] = None
        self._active_status_pattern: Optional[re.Pattern[bytes]] = None
        self._active_output = bytearray()
        self._buffer = bytearray()
        self._closed = False
        self._reaped = False
        pid, fd = pty.fork()
        if pid == 0:  # pragma: no cover - executed in child
            env = os.environ.copy()
            env.update({"PS1": "", "PS2": "", "TERM": "dumb"})
            os.execvpe(self.shell, [self.shell, "--noprofile", "--norc", "-i"], env)
            os._exit(127)
        self._pid, self._fd = pid, fd
        os.set_blocking(fd, False)
        self._disable_echo()
        self._drain_startup()

    def reset(self) -> None:
        """Discard all shell state and start a fresh session in this object.

        Any currently running command is terminated. The configured shell,
        timeout, and encoding are retained; working directory, environment
        changes, shell variables, buffered output, and command state are reset.
        """
        self.close()
        self._start_session()

    def run(self, command: str, timeout: Optional[float] = None) -> CommandResult:
        """Run a command in the persistent shell and collect its output.

        Commands execute in the existing shell, so changes to its working
        directory, environment, and shell variables persist across calls. The
        call returns when the command completes or no output arrives for the
        selected timeout; a quiet return may mean the command is still active.

        Args:
            command: Shell command text to evaluate.
            timeout: Maximum quiet period in seconds before returning. ``None``
                uses ``idle_timeout``; newly received output restarts the period.

        Returns:
            A result whose state is ``completed``, ``waiting_for_input``, or
            ``idle``.

        Raises:
            ValueError: If another command is active or ``timeout`` is negative.
            ShellSessionClosed: If the shell is not available.
        """
        self._ensure_open()
        if self._active_marker is not None:
            raise ValueError("A command is still active; poll or provide input first")
        self._validate_timeout(timeout)
        token = uuid.uuid4().hex.encode("ascii")
        marker, end = b"__PERSISTENT_SHELL_" + token + b":", b"__END_" + token + b"__"
        self._active_marker = marker
        self._active_status_pattern = re.compile(
            rb"\r?\n" + re.escape(marker) + rb"([0-9]+)" + re.escape(end) + rb"\r?\n?"
        )
        self._active_output.clear()
        # eval runs in the persistent shell, and the marker is emitted only
        # after it returns. The unique marker cannot be confused with output.
        wrapper = (
            f"eval {shlex.quote(command)}; "
            f"printf '\\n%s%s%s\\n' '{marker.decode()}' \"$?\" '{end.decode()}'\n"
        )
        self._write(wrapper)
        return self._wait(timeout)

    def send_input(self, text: str, *, newline: bool = True,
                   timeout: Optional[float] = None) -> CommandResult:
        """Send text to the active command, optionally pressing Enter.

        Args:
            text: Text to write to the shell's pseudo-terminal.
            newline: Whether to append a newline to ``text``.
            timeout: Quiet period to wait for more output; ``None`` uses
                ``idle_timeout``.

        Returns:
            Newly collected output and the command's current state.

        Raises:
            ValueError: If no command is active or ``timeout`` is negative.
            ShellSessionClosed: If the shell is not available.
        """
        self._ensure_open()
        if self._active_marker is None:
            raise ValueError("There is no active command")
        self._validate_timeout(timeout)
        self._write(text + ("\n" if newline else ""))
        return self._wait(timeout)

    def poll(self, timeout: Optional[float] = None) -> CommandResult:
        """Wait for and collect more output without sending input.

        Args:
            timeout: Quiet period to wait; ``None`` uses ``idle_timeout``.

        Returns:
            Newly collected output and the command's current state.

        Raises:
            ValueError: If no command is active or ``timeout`` is negative.
            ShellSessionClosed: If the shell is not available.
        """
        self._ensure_open()
        if self._active_marker is None:
            raise ValueError("There is no active command")
        self._validate_timeout(timeout)
        return self._wait(timeout)

    def close(self, grace_period: float = 1.0) -> None:
        """Terminate the shell process and release its pseudo-terminal.

        The shell first receives ``SIGHUP`` and is given up to ``grace_period``
        seconds to exit. If it remains alive, it is forcibly terminated.
        Repeated calls are safe.
        """
        self._closed = True
        if not self._reaped:
            try:
                os.killpg(self._pid, signal.SIGHUP)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + max(0.0, grace_period)
        while time.monotonic() < deadline:
            if self._reap_nonblocking():
                break
            time.sleep(0.02)
        if not self._reaped:
            try:
                os.killpg(self._pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(self._pid, 0)
            except ChildProcessError:
                pass
            self._reaped = True
        try:
            os.close(self._fd)
        except OSError:
            pass

    def __enter__(self) -> "PersistentShell":
        """Return this open session for use as a context manager."""
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Close the session when leaving a ``with`` block."""
        self.close()

    @staticmethod
    def _validate_timeout(timeout: Optional[float]) -> None:
        """Reject a negative timeout; ``None`` denotes the configured default."""
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be non-negative")

    def _wait(self, timeout: Optional[float]) -> CommandResult:
        """Collect output until completion or the next quiet-period deadline."""
        quiet_for = self.idle_timeout if timeout is None else timeout
        deadline = time.monotonic() + quiet_for
        while True:
            received = self._read_available(max(0.0, deadline - time.monotonic()))
            if received:
                deadline = time.monotonic() + quiet_for
            exit_code = self._extract_completion()
            if exit_code is not None:
                return self._result("completed", exit_code)
            if self._process_exited():
                self._closed = True
                raise ShellSessionClosed("The shell exited before the command completed")
            if time.monotonic() >= deadline:
                state = "waiting_for_input" if self._looks_like_prompt() else "idle"
                return self._result(state)

    def _looks_like_prompt(self) -> bool:
        """Return whether recent buffered terminal output matches a known prompt."""
        text = bytes(self._active_output + self._buffer).decode(self.encoding, errors="replace")
        text = self._ANSI_ESCAPE.sub("", text).replace("\r", "\n")
        return bool(self._PROMPT.search(text[-512:]))

    def _read_available(self, timeout: float) -> bool:
        """Read currently available PTY bytes, waiting at most ``timeout``.

        Returns whether any bytes were received. PTY ``EIO`` is treated as an
        end-of-stream condition, as it commonly occurs after the child exits.
        """
        received = False
        try:
            readable, _, _ = select.select([self._fd], [], [], timeout)
            if not readable:
                return False
            while True:
                try:
                    chunk = os.read(self._fd, 65536)
                except BlockingIOError:
                    break
                except OSError as exc:
                    if exc.errno == errno.EIO:  # PTY reports EIO after child exit.
                        break
                    raise
                if not chunk:
                    break
                self._buffer.extend(chunk)
                received = True
        except InterruptedError:
            pass
        return received

    def _extract_completion(self) -> Optional[int]:
        """Consume the command's completion marker and return its exit status.

        Output preceding the marker is retained for the next result. If the
        marker has not arrived, old buffer bytes are moved to that output while
        preserving enough trailing bytes to detect a marker split across reads.
        """
        pattern = self._active_status_pattern
        if pattern is None:
            return None
        match = pattern.search(self._buffer)
        if match is None:
            keep = len(self._active_marker or b"") + 64
            flush = max(0, len(self._buffer) - keep)
            if flush:
                self._active_output.extend(self._buffer[:flush])
                del self._buffer[:flush]
            return None
        status = match.group(1)  # Save before deleting: the match references this bytearray.
        self._active_output.extend(self._buffer[:match.start()])
        del self._buffer[:match.end()]
        self._active_marker = self._active_status_pattern = None
        # The marker is emitted by our own printf and should always carry a
        # numeric status; guard against a damaged/partial terminal stream.
        try:
            return int(status.decode("ascii"))
        except ValueError:
            return 1

    def _result(self, state: str, exit_code: Optional[int] = None) -> CommandResult:
        """Build a result from accumulated bytes and normalize terminal output."""
        # On an idle return, the marker look-behind may still be buffered.
        # Include all currently observed command output in this result.
        if self._buffer:
            self._active_output.extend(self._buffer)
            self._buffer.clear()
        data = bytes(self._active_output)
        self._active_output.clear()
        text = data.decode(self.encoding, errors="replace")
        text = self._ANSI_ESCAPE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
        # PTY applications may use backspace to erase terminal characters.
        cleaned = []
        for char in text:
            if char == "\b":
                if cleaned and cleaned[-1] != "\n":
                    cleaned.pop()
            else:
                cleaned.append(char)
        return CommandResult("".join(cleaned), state, exit_code)

    def _write(self, text: str) -> None:
        """Write all encoded text to the PTY, handling partial writes."""
        view = memoryview(text.encode(self.encoding))
        while view:
            try:
                written = os.write(self._fd, view)
            except OSError as exc:
                if exc.errno in (errno.EIO, errno.EBADF):
                    self._closed = True
                    raise ShellSessionClosed("Cannot write to the shell terminal") from exc
                raise
            if written == 0:
                raise ShellSessionClosed("Cannot write to the shell terminal")
            view = view[written:]

    def _disable_echo(self) -> None:
        """Disable PTY echo so input is not duplicated in captured output."""
        import termios
        attrs = termios.tcgetattr(self._fd)
        attrs[3] &= ~termios.ECHO
        termios.tcsetattr(self._fd, termios.TCSANOW, attrs)

    def _drain_startup(self) -> None:
        """Discard initial shell startup output so it cannot pollute results."""
        deadline = time.monotonic() + 0.1
        while time.monotonic() < deadline:
            try:
                readable, _, _ = select.select([self._fd], [], [], deadline - time.monotonic())
                if not readable:
                    break
                if not os.read(self._fd, 65536):
                    break
            except (OSError, InterruptedError):
                break

    def _reap_nonblocking(self) -> bool:
        """Check whether the child has exited and reap it without blocking."""
        if self._reaped:
            return True
        try:
            pid, _ = os.waitpid(self._pid, os.WNOHANG)
        except ChildProcessError:
            pid = self._pid
        if pid == self._pid:
            self._reaped = True
        return self._reaped

    def _process_exited(self) -> bool:
        """Return whether the shell child process has exited."""
        return self._reap_nonblocking()

    def _ensure_open(self) -> None:
        """Raise ``ShellSessionClosed`` if this session has been closed."""
        if self._closed:
            raise ShellSessionClosed("The shell session is closed")


if __name__ == "__main__":
    with PersistentShell() as shell:
        print(shell.run("printf 'hello\\n'"))
