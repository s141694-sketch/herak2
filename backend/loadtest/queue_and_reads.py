"""Light load test, parts (b) and (c) (task 8.2, spec 8.3, D82): the analysis queue under pressure, and the pages
people read while it drains.

  1. Setup: VERSIONS draft programs, each with a unit, a lesson and four blocks, through the API.
  2. Reads alone: USERS people, each in their own session, read programs, versions, trees, reports, tasks and
     notifications for SECONDS seconds.
  3. Reads during the queue: the same, while a full quality analysis is asked for every program at once and a real
     Celery worker (not run at once in the request) works through them; until the queue is empty.

    cd backend && uv run python loadtest/queue_and_reads.py

API (http://127.0.0.1:8000), DATABASE_URL (to watch the reports drain), REDIS_URL (the broker), EMAIL and
PASSWORD (the e2e seed's admin), VERSIONS (200), USERS (20), SECONDS (60), OUT (a JSON file). The standard library,
psycopg and redis only, which the backend already has.
"""

import http.cookiejar
import json
import os
import random
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request

import psycopg
import redis

API = os.environ.get("API", "http://127.0.0.1:8000")
EMAIL = os.environ.get("EMAIL", "multi@example.com")
PASSWORD = os.environ.get("PASSWORD", os.environ.get("E2E_PASSWORD", "harak-e2e-password"))
VERSIONS = int(os.environ.get("VERSIONS", 200))
USERS = int(os.environ.get("USERS", 20))
SECONDS = int(os.environ.get("SECONDS", 60))


class Session:
    """One signed-in person: their own cookies and CSRF token."""

    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.call("GET", "/api/auth/csrf/")
        session = self.call("POST", "/api/auth/login/", {"email": EMAIL, "password": PASSWORD})
        if (session.get("organization") or {}).get("slug") != "vtc":
            vtc = next(m["organization"] for m in session["memberships"] if m["organization"]["slug"] == "vtc")
            self.call("POST", "/api/auth/switch-organization/", {"organization_id": vtc["id"]})

    def call(self, method: str, path: str, body=None):
        token = next((c.value for c in self.jar if c.name == "csrftoken"), "")
        request = urllib.request.Request(
            API + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "X-CSRFToken": token, "Referer": API + "/"},
        )
        with self.opener.open(request, timeout=60) as response:
            data = response.read()
        return json.loads(data) if data else None


def paragraph(text: str) -> dict:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def set_up(session: Session) -> list[int]:
    stamp = str(int(time.time()))[-6:]
    levels = [{"name_ar": "وحدة", "name_en": "Module"}, {"name_ar": "درس", "name_en": "Lesson"}]
    template = session.call("POST", "/api/structure-templates/", {"name": f"طابور {stamp}", "levels": levels})
    session.call("POST", f"/api/template-versions/{template['versions'][0]['id']}/publish/")
    framework = session.call("POST", "/api/competency-frameworks/", {"name": f"طابور {stamp}"})
    fv = framework["versions"][0]["id"]
    competency = session.call("POST", f"/api/framework-versions/{fv}/competencies/", {"code": "Q-1", "title": "كفاية"})
    session.call("POST", f"/api/framework-versions/{fv}/publish/")
    versions = []
    for n in range(VERSIONS):
        program = session.call(
            "POST",
            "/api/programs/",
            {
                "title": f"برنامج الطابور {stamp}-{n}",
                "target_role": "فني",
                "template_version": template["versions"][0]["id"],
                "framework_version": fv,
                "targets": [competency["id"]],
            },
        )
        version = program["versions"][0]["id"]
        unit = session.call("POST", f"/api/program-versions/{version}/nodes/", {"title": "الوحدة الأولى"})
        lesson = session.call(
            "POST", f"/api/program-versions/{version}/nodes/", {"title": "الدرس الأول", "parent": unit["id"]}
        )
        for kind, text in (
            ("objective", "أن يحدد المتدرب مخاطر موقع العمل"),
            ("objective", "يعرف المتدرب المعدات"),
            ("content", "شرح المخاطر الشائعة في الموقع وطرق الوقاية منها."),
            ("activity", "جولة في الورشة لتحديد المخاطر."),
        ):
            session.call(
                "POST",
                f"/api/program-versions/{version}/blocks/",
                {"node": lesson["id"], "type": kind, "content": paragraph(text)},
            )
        versions.append(version)
    return versions


def reads(versions: list[int], stop: threading.Event, out: list, errors: list) -> None:
    session = Session()
    paths = {
        "programs": lambda: "/api/programs/",
        "version": lambda: f"/api/program-versions/{random.choice(versions)}/",
        "tree": lambda: f"/api/program-versions/{random.choice(versions)}/tree/",
        "quality": lambda: f"/api/program-versions/{random.choice(versions)}/quality/",
        "tasks": lambda: "/api/tasks/",
        "notifications": lambda: "/api/notifications/",
    }
    while not stop.is_set():
        kind = random.choice(list(paths))
        path = paths[kind]()
        started = time.monotonic()
        try:
            session.call("GET", path)
            out.append((kind, (time.monotonic() - started) * 1000))
        except Exception as exc:  # noqa: BLE001 - every failed read counts, and the reader goes on (phase 8 review)
            # urllib wraps only the request in URLError: a dropped connection, a cut-off or malformed answer
            # surfaced as other errors and ended the thread uncounted.
            errors.append(f"{path}: {type(exc).__name__}: {exc}")
        time.sleep(random.uniform(0.2, 0.6))  # a person reading, not a loop


def run_reads(versions: list[int], until) -> dict:
    stop, out, errors = threading.Event(), [], []
    threads = [threading.Thread(target=reads, args=(versions, stop, out, errors)) for _ in range(USERS)]
    for thread in threads:
        thread.start()
    started = time.monotonic()
    until(started)
    stop.set()
    for thread in threads:
        thread.join()
    return summary(out, errors, time.monotonic() - started)


def summary(measured: list[tuple[str, float]], errors: list[str], seconds: float) -> dict:
    result = _summary([ms for _, ms in measured], errors, seconds)
    kinds = sorted({kind for kind, _ in measured})
    result["by_page"] = {
        kind: _summary([ms for k, ms in measured if k == kind], [], seconds)["latency_ms"] for kind in kinds
    }
    return result


def _summary(latencies: list[float], errors: list[str], seconds: float) -> dict:
    ordered = sorted(latencies)
    at = lambda p: round(ordered[min(len(ordered) - 1, int(p / 100 * len(ordered)))], 1) if ordered else None  # noqa: E731
    return {
        "requests": len(ordered),
        "per_second": round(len(ordered) / seconds, 1),
        "errors": len(errors),
        "first_errors": errors[:5],
        "latency_ms": {"p50": at(50), "p95": at(95), "p99": at(99), "max": round(ordered[-1], 1) if ordered else None},
        "mean_ms": round(statistics.mean(ordered), 1) if ordered else None,
        "seconds": round(seconds, 1),
    }


def statuses(versions: list[int]) -> dict:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute(
            "SELECT status, count(*) FROM quality_qualityreport"
            " WHERE version_id = ANY(%s) AND last_run = 'full' GROUP BY status",
            (versions,),
        ).fetchall()
    return dict(rows)


def queue_empty(timeout: int = 1800) -> float:
    """Waits until the worker has taken every queued task (the light checks the setup's saves asked for)."""
    queue = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6380/4"))
    started = time.monotonic()
    while queue.llen("celery") and time.monotonic() - started < timeout:
        time.sleep(2)
    return round(time.monotonic() - started, 1)


def main() -> int:
    admin = Session()
    setup_started = time.monotonic()
    versions = set_up(admin)
    setup_seconds = round(time.monotonic() - setup_started, 1)
    print(f"set up {len(versions)} programs in {setup_seconds} s", file=sys.stderr)
    settled = queue_empty()
    print(f"the setup's light checks drained in {settled} s", file=sys.stderr)

    alone = run_reads(versions, lambda started: time.sleep(SECONDS))
    print("reads alone:", json.dumps(alone), file=sys.stderr)

    drained = {}

    def queue_then_wait(started):
        for version in versions:
            admin.call("POST", f"/api/program-versions/{version}/quality/run/")
        drained["asked_seconds"] = round(time.monotonic() - started, 1)
        while True:
            now = statuses(versions)
            if sum(now.get(s, 0) for s in ("complete", "partial_rules_only", "failed")) >= len(versions):
                break
            if time.monotonic() - started > 1800:
                drained["timed_out"] = True
                break
            time.sleep(2)
        drained["seconds"] = round(time.monotonic() - started, 1)
        drained["statuses"] = statuses(versions)

    during = run_reads(versions, queue_then_wait)
    report = {
        "users": USERS,
        "programs": len(versions),
        "setup_seconds": setup_seconds,
        "reads_alone": alone,
        "reads_during_queue": during,
        "queue": {**drained, "runs_per_minute": round(len(versions) / drained["seconds"] * 60, 1)},
        "p95_ratio": round(during["latency_ms"]["p95"] / alone["latency_ms"]["p95"], 2),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if os.environ.get("OUT"):
        with open(os.environ["OUT"], "w") as out:
            json.dump(report, out, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
