"""The worker's logs and printed output reach its log, as the web process's do (D101).

Celery sets up logging itself when a worker or beat starts. Each test runs that setup in a fresh process, as
`celery worker` does, because it replaces sys.stdout and the logging configuration of the process it runs in.
"""

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3]

WORKER_START = """
import logging
from django.core.mail import EmailMessage
from config.celery import app

# What `celery worker` does before it takes tasks (celery/apps/worker.py, setup_logging).
app.log.setup(loglevel="INFO", redirect_stdouts=True, redirect_level="WARNING")
logging.getLogger("celery.app.trace").error("Task accounts.send_invitation raised: SMTP refused")
EmailMessage("دعوة", "https://harak.example.test/set-password?uid=1", "a@example.com", ["b@example.com"]).send()
"""


def run_worker_start():
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.test",
        "LOG_LEVEL": "INFO",
        "EMAIL_URL": "consolemail://",
        "PYTHONUNBUFFERED": "1",
    }
    script = "import django; django.setup()\n" + WORKER_START
    return subprocess.run(
        [sys.executable, "-c", script], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120
    )


def test_a_failing_task_is_logged():
    result = run_worker_start()
    assert result.returncode == 0, result.stderr
    assert "Task accounts.send_invitation raised: SMTP refused" in result.stdout + result.stderr


def test_an_email_printed_by_the_console_backend_reaches_the_log_as_written():
    # infra/print-emails.py reads it from the worker's log: each email starts a line with its Content-Type.
    result = run_worker_start()
    assert result.returncode == 0, result.stderr
    lines = (result.stdout + result.stderr).splitlines()
    assert any(line.startswith("Content-Type: text/plain") for line in lines)
    assert any(line.startswith("-" * 79) for line in lines)
