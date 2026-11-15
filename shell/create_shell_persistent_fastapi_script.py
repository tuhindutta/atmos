import os
import subprocess
from pathlib import Path

class Shell:
    def __init__(self, python_runtime_path: str, path: str, port: int):
        self.python_runtime_path = python_runtime_path
        self.port = port
        self.path = path
        self._process: subprocess.Popen[bytes] | None = None

    def create_shell_instance(self):
        with open("shell/persistent_shell_api.txt", "r") as f:
            txt = f.read().replace("port_assignment", str(self.port))
        with open(self.path, "w") as f:
            f.write(txt)

    def launch(self) -> subprocess.Popen[bytes]:
        """Start the FastAPI script without blocking and return its process."""
        if self._process is not None and self._process.poll() is None:
            raise RuntimeError("The FastAPI server is already running")
        project_root = Path(__file__).resolve().parent.parent
        script_path = Path(self.path).expanduser().resolve()
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            path
            for path in (str(project_root), env.get("PYTHONPATH"))
            if path
        )
        self._process = subprocess.Popen(
            [self.python_runtime_path, str(script_path)],
            cwd=project_root,
            env=env,
        )
        return self._process

    def stop(self) -> bool:
        """Stop the process using this shell's TCP port.

        Returns ``True`` if a process was found and signalled, or ``False`` if
        the port was not in use. Uses ``fuser`` to send SIGTERM to the process.
        """
        try:
            result = subprocess.run(
                ["fuser", "-k", "-TERM", f"{self.port}/tcp"],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("The fuser utility is required to stop the server") from exc

        if result.returncode == 0:
            return True
        if result.returncode == 1 and not result.stderr.strip():
            return False
        raise RuntimeError(result.stderr.strip() or "Failed to stop the server")

    def delete_shell_instance(self) -> bool:
        """Delete the generated API script, returning whether it existed."""
        try:
            Path(self.path).expanduser().unlink()
        except FileNotFoundError:
            return False
        return True

