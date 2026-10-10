from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.config import settings_from_env
from app.main import create_app


@pytest.fixture
def make_settings(tmp_path: Path):
    def _make(**overrides: str):
        env = {
            "APP_ENV": "test",
            "TEMP_DIR": str(tmp_path / "splice-tmp"),
            # Real Whisper is exercised by the opt-in integration test; API tests stay fast & offline.
            "WHISPER_ENGINE": "none",
            "RATE_LIMIT_JOBS_PER_HOUR": "0",
            "MIN_FREE_DISK_MB": "0",
            "LOG_LEVEL": "WARNING",
        }
        env.update({k.upper(): str(v) for k, v in overrides.items()})
        return settings_from_env(env)

    return _make


@pytest.fixture
def client_factory(make_settings):
    clients: list[TestClient] = []

    def _factory(**overrides: str) -> TestClient:
        client = TestClient(create_app(make_settings(**overrides)))
        client.__enter__()
        clients.append(client)
        return client

    yield _factory
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(client_factory) -> Iterator[TestClient]:
    yield client_factory()


def wait_for_terminal(client: TestClient, job_id: str, token: str, timeout: float = 120) -> dict:
    deadline = time.monotonic() + timeout
    seen: list[str] = []
    while time.monotonic() < deadline:
        body = client.get(f"/api/jobs/{job_id}", headers={"X-Job-Token": token}).json()
        if not seen or seen[-1] != body["status"]:
            seen.append(body["status"])
        if body["status"] in ("completed", "failed", "cancelled", "expired"):
            body["_seen"] = seen
            return body
        time.sleep(0.1)
    raise AssertionError(f"job did not finish in {timeout}s; states seen: {seen}")


def upload(client: TestClient, path: Path, settings: dict | None = None, name: str | None = None):
    import json

    with path.open("rb") as fh:
        files = {"file": (name or path.name, fh, "video/mp4")}
        data = {"settings": json.dumps(settings)} if settings is not None else {}
        return client.post("/api/jobs", files=files, data=data)
