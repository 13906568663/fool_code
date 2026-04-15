"""Bash tool — execute shell commands.

  - ShellProvider abstraction (bash on Unix, PowerShell on Windows)
  - CWD tracking across commands via temp file
  - Default 30-minute timeout
  - stdin protection (DEVNULL)
  - Command quoting for eval (heredoc / multiline aware)
  - Windows >nul → >$null rewriting
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from fool_code.runtime.config import active_workspace_root

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MS = 30 * 60 * 1000  # 30 minutes
MAX_OUTPUT_CHARS = 50_000

# ---------------------------------------------------------------------------
# CWD state — tracked across commands within a session
# ---------------------------------------------------------------------------

_cwd_lock = threading.Lock()
_current_cwd: str | None = None


def get_effective_cwd() -> str:
    with _cwd_lock:
        if _current_cwd and os.path.isdir(_current_cwd):
            return _current_cwd
    return str(active_workspace_root())


def _set_cwd(new_cwd: str) -> None:
    global _current_cwd
    resolved = os.path.realpath(new_cwd)
    if os.path.isdir(resolved):
        with _cwd_lock:
            _current_cwd = resolved
        logger.debug("CWD updated → %s", resolved)


def reset_cwd() -> None:
    global _current_cwd
    with _cwd_lock:
        _current_cwd = None


# ---------------------------------------------------------------------------
# Windows >nul rewrite (CMD-style null redirect → PowerShell $null)
# ---------------------------------------------------------------------------

_NUL_REDIRECT_RE = re.compile(
    r"(\d?&?>+\s*)[Nn][Uu][Ll](?=\s|$|[|&;)\n])",
)


def _rewrite_windows_nul(command: str) -> str:
    """Rewrite CMD-style ``>nul`` to ``>$null`` for PowerShell."""
    return _NUL_REDIRECT_RE.sub(r"\g<1>$null", command)


# ---------------------------------------------------------------------------
# Shell detection helpers
# ---------------------------------------------------------------------------

def _find_powershell() -> str | None:
    for candidate in ("pwsh", "powershell"):
        p = shutil.which(candidate)
        if p:
            return p
    return None


def _find_bash() -> str | None:
    p = shutil.which("bash")
    if p:
        return p
    if sys.platform == "win32":
        for candidate in (
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
        ):
            if os.path.isfile(candidate):
                return candidate
    return None


# ---------------------------------------------------------------------------
# Command quoting helpers
# ---------------------------------------------------------------------------

_HEREDOC_RE = re.compile(r"<<-?\s*(?:(['\"]?)(\w+)\1|\\(\w+))")


def _contains_heredoc(command: str) -> bool:
    if re.search(r"\d\s*<<\s*\d", command):
        return False
    return bool(_HEREDOC_RE.search(command))


def _contains_multiline(command: str) -> bool:
    return bool(
        re.search(r"'(?:[^'\\]|\\.)*\n(?:[^'\\]|\\.)*'", command)
        or re.search(r'"(?:[^"\\]|\\.)*\n(?:[^"\\]|\\.)*"', command)
    )


def _shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def _quote_for_eval(command: str, add_stdin_redirect: bool) -> str:
    """Quote a command for ``eval '…'`` execution."""
    if _contains_heredoc(command) or _contains_multiline(command):
        escaped = command.replace("'", "'\"'\"'")
        quoted = f"'{escaped}'"
        if _contains_heredoc(command):
            return quoted
        return f"{quoted} < /dev/null" if add_stdin_redirect else quoted

    escaped = command.replace("'", "'\"'\"'")
    quoted = f"'{escaped}'"
    return f"{quoted} < /dev/null" if add_stdin_redirect else quoted


def _should_add_stdin_redirect(command: str) -> bool:
    if _contains_heredoc(command):
        return False
    if re.search(r"(?:^|[\s;&|])<(?![<(])\s*\S+", command):
        return False
    return True


# ---------------------------------------------------------------------------
# Shell providers
# ---------------------------------------------------------------------------

class _PowerShellProvider:
    """Windows PowerShell provider.

    Uses PowerShell as the execution shell. This solves the ``cmd /C`` pipe
    mangling bug — PowerShell handles ``|``, ``$``, etc. natively.
    Also appends CWD tracking via ``(Get-Location).Path``.
    """

    def __init__(self, ps_path: str) -> None:
        self._path = ps_path

    @property
    def shell_path(self) -> str:
        return self._path

    def build_exec_args(
        self, command: str, cwd: str, cwd_file: str,
    ) -> list[str]:
        command = _rewrite_windows_nul(command)
        escaped_cwd = cwd_file.replace("'", "''")
        # Exit-code capture: prefer $LASTEXITCODE for native exe,
        # fall back to $? for cmdlet-only pipelines.
        ps_command = (
            "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
            f"{command}"
            "; $_ec = if ($null -ne $LASTEXITCODE) { $LASTEXITCODE } "
            "elseif ($?) { 0 } else { 1 }"
            f"; (Get-Location).Path | Out-File -FilePath '{escaped_cwd}' "
            "-Encoding utf8 -NoNewline"
            "; exit $_ec"
        )
        return [self._path, "-NoProfile", "-NonInteractive", "-Command", ps_command]


class _BashProvider:
    """Unix / Git-Bash provider.

    Uses ``eval`` wrapping with proper quoting. Appends ``pwd -P`` for
    CWD tracking and redirects stdin to ``/dev/null`` for safety.
    """

    def __init__(self, bash_path: str) -> None:
        self._path = bash_path

    @property
    def shell_path(self) -> str:
        return self._path

    def build_exec_args(
        self, command: str, cwd: str, cwd_file: str,
    ) -> list[str]:
        add_stdin = _should_add_stdin_redirect(command)
        quoted = _quote_for_eval(command, add_stdin)
        parts = [
            f"eval {quoted}",
            f"pwd -P >| {_shell_quote(cwd_file)}",
        ]
        return [self._path, "-l", "-c", " && ".join(parts)]


class _CmdFallbackProvider:
    """Last-resort cmd.exe provider (should rarely be used)."""

    @property
    def shell_path(self) -> str:
        return "cmd"

    def build_exec_args(
        self, command: str, cwd: str, cwd_file: str,
    ) -> list[str]:
        wrapped = f'chcp 65001 >nul && {command} && cd > "{cwd_file}"'
        return ["cmd", "/C", wrapped]


# Provider type alias
_Provider = _PowerShellProvider | _BashProvider | _CmdFallbackProvider

# ---------------------------------------------------------------------------
# Provider selection (cached per-process)
# ---------------------------------------------------------------------------

_cached_provider: _Provider | None = None


def _get_provider() -> _Provider:
    global _cached_provider
    if _cached_provider is not None:
        return _cached_provider

    if sys.platform == "win32":
        ps = _find_powershell()
        if ps:
            _cached_provider = _PowerShellProvider(ps)
            logger.info("Shell provider: PowerShell (%s)", ps)
            return _cached_provider
        _cached_provider = _CmdFallbackProvider()
        logger.warning("Shell provider: cmd.exe (PowerShell not found)")
    else:
        bash = _find_bash() or "/bin/bash"
        _cached_provider = _BashProvider(bash)
        logger.info("Shell provider: bash (%s)", bash)

    return _cached_provider


# ---------------------------------------------------------------------------
# CWD tracking helper
# ---------------------------------------------------------------------------

def _update_cwd_from_file(cwd_file: str) -> None:
    try:
        raw = Path(cwd_file).read_text(encoding="utf-8").strip()
        # PowerShell may write BOM; strip it
        raw = raw.lstrip("\ufeff").strip()
        if raw and os.path.isdir(raw):
            _set_cwd(raw)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def execute_bash(args: dict[str, Any], context: Any = None) -> str:
    command = args.get("command", "")
    if not command:
        raise ValueError("command is required")

    timeout_ms: int | None = args.get("timeout")
    run_in_background = args.get("run_in_background", False)
    is_windows = sys.platform == "win32"

    cwd = get_effective_cwd()
    provider = _get_provider()

    # --- background ---
    if run_in_background:
        child = _spawn_background(command, cwd, provider)
        return json.dumps({
            "stdout": "",
            "stderr": "",
            "interrupted": False,
            "backgroundTaskId": str(child.pid),
            "backgroundedByUser": False,
            "assistantAutoBackgrounded": False,
            "noOutputExpected": True,
        }, ensure_ascii=False, indent=2)

    # --- foreground ---
    if timeout_ms is None:
        timeout_ms = DEFAULT_TIMEOUT_MS
    timeout_sec = timeout_ms / 1000.0
    started = time.monotonic()

    on_progress = None
    if context and hasattr(context, "on_progress"):
        on_progress = context.on_progress

    cwd_file = os.path.join(
        tempfile.gettempdir(),
        f"foolcode-cwd-{os.getpid()}-{id(command) & 0xFFFF:04x}",
    )

    try:
        proc_args = provider.build_exec_args(command, cwd, cwd_file)

        proc = subprocess.Popen(
            proc_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            cwd=cwd,
            creationflags=0x08000000 if is_windows else 0,
        )

        stdout_lines: list[str] = []
        stderr_data = b""

        if on_progress and proc.stdout:
            try:
                for raw_line in iter(proc.stdout.readline, b""):
                    line = raw_line.decode("utf-8", errors="replace")
                    stdout_lines.append(line)
                    on_progress(line.rstrip("\n"))

                    if time.monotonic() - started > timeout_sec:
                        proc.kill()
                        stderr_data = (proc.stderr.read() if proc.stderr else b"") or b""
                        duration = int((time.monotonic() - started) * 1000)
                        return json.dumps(_build_output(
                            stdout="".join(stdout_lines),
                            stderr=stderr_data.decode("utf-8", errors="replace")
                                   + f"\nCommand exceeded timeout of {timeout_ms} ms",
                            interrupted=True, exit_code=None, duration_ms=duration,
                            return_code_interpretation="timeout",
                        ), ensure_ascii=False, indent=2)
            except Exception:
                pass

            stderr_data = (proc.stderr.read() if proc.stderr else b"") or b""
            proc.wait()
        else:
            try:
                out, err = proc.communicate(timeout=timeout_sec)
                stdout_lines.append(out.decode("utf-8", errors="replace"))
                stderr_data = err
            except subprocess.TimeoutExpired:
                proc.kill()
                out, err = proc.communicate()
                stdout_lines.append(
                    out.decode("utf-8", errors="replace") if out else ""
                )
                stderr_data = err or b""
                duration = int((time.monotonic() - started) * 1000)
                stderr_text = stderr_data.decode("utf-8", errors="replace")
                extra = f"\nCommand exceeded timeout of {timeout_ms} ms"
                stderr_text = (stderr_text + extra) if stderr_text.strip() else extra.lstrip()
                return json.dumps(_build_output(
                    stdout="".join(stdout_lines), stderr=stderr_text,
                    interrupted=True, exit_code=None, duration_ms=duration,
                    return_code_interpretation="timeout",
                ), ensure_ascii=False, indent=2)

        duration = int((time.monotonic() - started) * 1000)
        stdout = "".join(stdout_lines)
        stderr = stderr_data.decode("utf-8", errors="replace")
        exit_code = proc.returncode

        _update_cwd_from_file(cwd_file)

        return json.dumps(_build_output(
            stdout=stdout, stderr=stderr, interrupted=False,
            exit_code=exit_code, duration_ms=duration,
        ), ensure_ascii=False, indent=2)

    except Exception as exc:
        return json.dumps(_build_output(
            stdout="", stderr=str(exc), interrupted=False,
            exit_code=1, duration_ms=int((time.monotonic() - started) * 1000),
        ), ensure_ascii=False, indent=2)
    finally:
        try:
            os.unlink(cwd_file)
        except OSError:
            pass


def _spawn_background(
    command: str, cwd: str, provider: _Provider,
) -> subprocess.Popen:
    cwd_file = os.path.join(
        tempfile.gettempdir(), f"foolcode-bg-{os.getpid()}-{time.monotonic_ns() & 0xFFFF:04x}",
    )
    proc_args = provider.build_exec_args(command, cwd, cwd_file)
    return subprocess.Popen(
        proc_args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=cwd,
        creationflags=0x08000000 if sys.platform == "win32" else 0,
    )


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _build_output(
    *,
    stdout: str,
    stderr: str,
    interrupted: bool,
    exit_code: int | None,
    duration_ms: int,
    return_code_interpretation: str | None = None,
) -> dict[str, Any]:
    if return_code_interpretation is None and exit_code is not None and exit_code != 0:
        return_code_interpretation = f"exit_code:{exit_code}"

    stdout = _cap_output(stdout)
    stderr = _cap_output(stderr)

    result: dict[str, Any] = {
        "stdout": stdout,
        "stderr": stderr,
        "interrupted": interrupted,
    }

    if return_code_interpretation:
        result["returnCodeInterpretation"] = return_code_interpretation
    result["noOutputExpected"] = not stdout.strip() and not stderr.strip()
    result["durationMs"] = duration_ms

    return result


def _cap_output(s: str, max_len: int = MAX_OUTPUT_CHARS) -> str:
    if len(s) <= max_len:
        return s
    half = max_len // 2
    return s[:half] + "\n\n... (output truncated) ...\n\n" + s[-half:]
