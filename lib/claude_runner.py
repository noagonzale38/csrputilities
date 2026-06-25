import asyncio
import os
import shutil
from pathlib import Path
from typing import Awaitable, Callable, Optional

from config import BASE_DIR

CLAUDE_WORKDIR = BASE_DIR
CLAUDE_CLI_CANDIDATES = [
    shutil.which("claude"),
    str(Path.home() / ".local" / "bin" / "claude"),
    "/usr/local/bin/claude",
    "/snap/bin/claude",
]


def resolve_claude_cli() -> str:
    for candidate in CLAUDE_CLI_CANDIDATES:
        if not candidate:
            continue
        candidate_path = Path(candidate)
        if candidate_path.exists() and os.access(candidate_path, os.X_OK):
            return str(candidate_path)

    raise FileNotFoundError(
        "Unable to locate the Claude CLI. Checked: "
        + ", ".join(candidate for candidate in CLAUDE_CLI_CANDIDATES if candidate)
    )


def _claude_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = ":".join(
        part for part in [
            str(Path.home() / ".local" / "bin"),
            "/usr/local/bin",
            "/snap/bin",
            env.get("PATH", ""),
        ] if part
    )
    return env


def _claude_command(prompt: str) -> list[str]:
    claude_cli = resolve_claude_cli()
    return [
        claude_cli,
        "-p",
        prompt,
        "--output-format", "text",
        "--dangerously-skip-permissions",
    ]


class ClaudeRunControl:
    def __init__(self) -> None:
        self.process: Optional[asyncio.subprocess.Process] = None
        self.stop_requested = False

    def attach(self, process: asyncio.subprocess.Process) -> None:
        self.process = process

    async def stop(self) -> bool:
        self.stop_requested = True
        if self.process is None or self.process.returncode is not None:
            return False

        self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=5)
        except asyncio.TimeoutError:
            self.process.kill()
            await self.process.wait()
        return True


async def stream_claude_prompt(
    prompt: str,
    on_update: Optional[Callable[[str, str, bool], Awaitable[None]]] = None,
    update_interval: int = 15,
    control: Optional[ClaudeRunControl] = None,
) -> tuple[int, str, str]:
    command = _claude_command(prompt)
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(CLAUDE_WORKDIR),
        env=_claude_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    if control:
        control.attach(process)

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    queue: asyncio.Queue[tuple[str, Optional[str]]] = asyncio.Queue()

    async def read_stream(stream, name: str):
        while True:
            line = await stream.readline()
            if not line:
                await queue.put((name, None))
                break
            await queue.put((name, line.decode("utf-8", errors="replace")))

    stdout_task = asyncio.create_task(read_stream(process.stdout, "stdout"))
    stderr_task = asyncio.create_task(read_stream(process.stderr, "stderr"))
    finished_streams = set()
    last_sent_state = ("", "")

    while len(finished_streams) < 2:
        try:
            source, payload = await asyncio.wait_for(queue.get(), timeout=update_interval)
        except asyncio.TimeoutError:
            if on_update:
                current_state = ("".join(stdout_chunks), "".join(stderr_chunks))
                if current_state != last_sent_state:
                    await on_update(current_state[0], current_state[1], False)
                    last_sent_state = current_state
            continue

        if payload is None:
            finished_streams.add(source)
            continue

        if source == "stdout":
            stdout_chunks.append(payload)
        else:
            stderr_chunks.append(payload)

        while not queue.empty():
            buffered_source, buffered_payload = queue.get_nowait()
            if buffered_payload is None:
                finished_streams.add(buffered_source)
            elif buffered_source == "stdout":
                stdout_chunks.append(buffered_payload)
            else:
                stderr_chunks.append(buffered_payload)

    await asyncio.gather(stdout_task, stderr_task)
    return_code = await process.wait()
    stdout = "".join(stdout_chunks)
    stderr = "".join(stderr_chunks)

    if on_update:
        await on_update(stdout, stderr, True)

    return (return_code, stdout, stderr)


async def run_claude_prompt(prompt: str) -> tuple[int, str, str]:
    command = _claude_command(prompt)
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(CLAUDE_WORKDIR),
        env=_claude_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return (
        process.returncode,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )
