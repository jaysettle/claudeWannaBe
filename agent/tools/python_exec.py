from __future__ import annotations

"""
Sandboxed Python execution helper for jay-agent.
Executes code in a subprocess, with optional file payloads, dependency install, and time/memory limits.
"""

import json
import os
import sys
import tempfile
import time
import uuid
import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import resource
except ImportError:  # pragma: no cover - non-POSIX
    resource = None  # type: ignore


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    result: Any
    exception: Optional[dict]
    locals: Dict[str, Any]
    files_written: List[str]
    execution_time: float


@dataclass
class Workspace:
    root: Path
    files_written: List[str]
    session_id: str
    persisted: bool
    deps_path: Path


class PythonExecutor:
    def __init__(self, settings):
        self.settings = settings
        self.global_env = Path("~/.jay-agent/python_env").expanduser()

    def execute(
        self,
        code: str,
        timeout: float,
        persist: bool = False,
        globals_mode: bool = True,
        files: Optional[List[dict]] = None,
        requirements: Optional[List[str]] = None,
        session_id: Optional[str] = None,
        max_memory_mb: Optional[int] = None,
    ) -> ExecResult:
        start = time.perf_counter()
        workspace = self._prepare_workspace(files or [], persist, session_id)
        req_paths: List[Path] = []
        if requirements:
            req_paths.append(self._install_requirements(requirements, workspace))
        runner = self._build_runner_script(code, workspace, globals_mode, req_paths)
        env = self._build_env(req_paths, workspace)
        proc = self._spawn_subprocess(runner, workspace, timeout, max_memory_mb, env)
        result = self._parse_result(proc, start, workspace)
        if not persist:
            self._cleanup(workspace)
        return result

    def _prepare_workspace(self, files: List[dict], persist: bool, session_id: Optional[str]) -> Workspace:
        if persist and session_id:
            root = Path(tempfile.gettempdir()) / "agent-python" / f"session_{session_id}"
            root.mkdir(parents=True, exist_ok=True)
        else:
            root = Path(tempfile.mkdtemp(prefix="agent-python-"))
        written: List[str] = []
        for f in files:
            rel = Path(f.get("path", ""))
            content = f.get("content", "")
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            written.append(str(rel))
        deps_path = root / "deps"
        deps_path.mkdir(exist_ok=True)
        return Workspace(root=root, files_written=written, session_id=session_id or uuid.uuid4().hex, persisted=persist, deps_path=deps_path)

    def _install_requirements(self, requirements: List[str], workspace: Workspace) -> Path:
        target = workspace.deps_path
        cmd = ["python3", "-m", "pip", "install", "--quiet", "--target", str(target), *requirements]
        subprocess.run(cmd, check=False)
        return target

    def _build_env(self, req_paths: List[Path], workspace: Workspace) -> Dict[str, str]:
        env = os.environ.copy()
        paths = [str(p) for p in req_paths if p.exists()]
        if paths:
            env["PYTHONPATH"] = os.pathsep.join(paths + env.get("PYTHONPATH", "").split(os.pathsep))
        env["PYTHONUNBUFFERED"] = "1"
        return env

    def _build_runner_script(
        self,
        code: str,
        workspace: Workspace,
        globals_mode: bool,
        req_paths: List[Path],
    ) -> Path:
        runner = workspace.root / "runner.py"
        marker = "===PYEXEC_JSON==="
        safe_builtins = "{}" if globals_mode else "{k:v for k,v in __builtins__.__dict__.items() if k in ['__name__','__doc__','__package__','__loader__','__spec__','__build_class__','__import__']}"
        runner.write_text(
            f"""
import asyncio, json, sys, traceback, time, io, contextlib
import builtins
SAFE_BUILTINS = {safe_builtins}
def maybe_json(val):
    try:
        json.dumps(val)
        return val
    except Exception:
        return str(val)

def summarize_locals(ns):
    out = {{}}
    for k,v in ns.items():
        if k.startswith("__"):
            continue
        try:
            out[k] = str(v)
        except Exception:
            out[k] = "<unrepr>"
    return out

async def _run_async(main_fn):
    return await main_fn()

def main():
    start = time.perf_counter()
    buf_out, buf_err = io.StringIO(), io.StringIO()
    ns = {{}}
    if SAFE_BUILTINS:
        ns["__builtins__"] = SAFE_BUILTINS
    result = None
    exc = None
    try:
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            exec({code!r}, ns, ns)
            if "main" in ns and asyncio.iscoroutinefunction(ns["main"]):
                result = asyncio.run(ns["main"]())
            elif "main" in ns and callable(ns["main"]):
                result = ns["main"]()
    except Exception as e:
        exc = {{
            "type": e.__class__.__name__,
            "message": str(e),
            "traceback": traceback.format_exc(),
        }}
    payload = {{
        "stdout": buf_out.getvalue(),
        "stderr": buf_err.getvalue(),
        "result": maybe_json(result),
        "exception": exc,
        "locals": summarize_locals(ns),
        "files_written": {workspace.files_written!r},
        "execution_time": time.perf_counter() - start,
    }}
    print("{marker}" + json.dumps(payload, default=str))

if __name__ == "__main__":
    main()
""",
            encoding="utf-8",
        )
        return runner

    def _spawn_subprocess(
        self,
        runner: Path,
        workspace: Workspace,
        timeout: float,
        memory_limit_mb: Optional[int],
        env: Dict[str, str],
    ) -> subprocess.CompletedProcess:
        # On macOS, preexec_fn can cause issues with fork() in interactive sessions
        # Disable memory limits on Darwin (macOS) to avoid crashes
        import platform
        is_macos = platform.system() == 'Darwin'

        def set_limits():
            if resource and memory_limit_mb:
                try:
                    bytes_limit = memory_limit_mb * 1024 * 1024
                    resource.setrlimit(resource.RLIMIT_AS, (bytes_limit, bytes_limit))
                except Exception:
                    # Silently ignore if setrlimit fails
                    pass

        # Disable preexec_fn on macOS to avoid fork() issues
        use_preexec = resource and memory_limit_mb and not is_macos

        return subprocess.run(
            ["python3", str(runner)],
            cwd=workspace.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            preexec_fn=set_limits if use_preexec else None,
        )

    def _parse_result(self, proc: subprocess.CompletedProcess, start: float, workspace: Workspace) -> ExecResult:
        marker = "===PYEXEC_JSON==="
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        payload = None
        if marker in stdout:
            try:
                payload = json.loads(stdout.split(marker)[-1].strip())
            except Exception:
                payload = None
        if not payload and marker in stderr:
            try:
                payload = json.loads(stderr.split(marker)[-1].strip())
            except Exception:
                payload = None

        if payload:
            return ExecResult(
                stdout=payload.get("stdout", ""),
                stderr=payload.get("stderr", ""),
                result=payload.get("result"),
                exception=payload.get("exception"),
                locals=payload.get("locals", {}),
                files_written=payload.get("files_written", []),
                execution_time=payload.get("execution_time", time.perf_counter() - start),
            )
        return ExecResult(
            stdout=stdout,
            stderr=stderr,
            result=None,
            exception={"type": "ExecutionError", "message": "Failed to parse result", "returncode": proc.returncode},
            locals={},
            files_written=workspace.files_written,
            execution_time=time.perf_counter() - start,
        )

    def _cleanup(self, workspace: Workspace):
        try:
            shutil.rmtree(workspace.root)
        except Exception:
            pass
