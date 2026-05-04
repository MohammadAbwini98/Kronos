from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Any

from logging_utils import log_event, output_tail, safe_command_for_log


def run_logged_subprocess(
    cmd: list[str],
    logger: logging.Logger,
    event_prefix: str,
    cwd: str | Path | None = None,
    timeout: int | None = None,
    context: dict[str, Any] | None = None,
) -> subprocess.CompletedProcess[str]:
    context_fields = dict(context or {})
    safe_cmd = safe_command_for_log(cmd)
    start = time.perf_counter()

    log_event(
        logger,
        logging.INFO,
        f"{event_prefix}.start",
        command=safe_cmd,
        cwd=str(cwd) if cwd else None,
        timeout=timeout,
        **context_fields,
    )

    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        combined = (exc.stdout or "") + ("\n" + exc.stderr if exc.stderr else "")
        log_event(
            logger,
            logging.ERROR,
            f"{event_prefix}.timeout",
            command=safe_cmd,
            duration_ms=duration_ms,
            timeout=timeout,
            output_tail=output_tail(combined),
            **context_fields,
        )
        raise

    duration_ms = int((time.perf_counter() - start) * 1000)
    combined = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")

    if result.returncode == 0:
        log_event(
            logger,
            logging.INFO,
            f"{event_prefix}.completed",
            command=safe_cmd,
            returncode=int(result.returncode),
            duration_ms=duration_ms,
            stdout_chars=len(result.stdout or ""),
            stderr_chars=len(result.stderr or ""),
            **context_fields,
        )
    else:
        log_event(
            logger,
            logging.ERROR,
            f"{event_prefix}.error",
            command=safe_cmd,
            returncode=int(result.returncode),
            duration_ms=duration_ms,
            output_tail=output_tail(combined),
            **context_fields,
        )

    return result
