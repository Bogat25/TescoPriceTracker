"""Run the two-store integration suite against a disposable local MongoDB."""

import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from pymongo import MongoClient
from pymongo.errors import PyMongoError


ROOT = Path(__file__).resolve().parents[1]


def main():
    if (ROOT / ".env").exists() or any(name in os.environ for name in ("DOCKER_HOST", "DOCKER_CONTEXT")):
        raise SystemExit("Use a clean checkout and the default local Docker context")
    endpoint = subprocess.check_output(
        ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], text=True).strip()
    if not endpoint.startswith("unix://"):
        raise SystemExit("Integration tests require a local Unix-socket Docker Engine")
    name = "tesco-linux-test-" + uuid.uuid4().hex[:12]
    container = subprocess.check_output(
        ["docker", "run", "--detach", "--rm", "--name", name,
         "--publish", "127.0.0.1::27017", "mongo:8"], text=True).strip()
    try:
        port = subprocess.check_output(
            ["docker", "port", container, "27017/tcp"], text=True).strip().rsplit(":", 1)[1]
        uri = "mongodb://127.0.0.1:" + port + "/"
        deadline = time.monotonic() + 90
        with MongoClient(uri, serverSelectionTimeoutMS=1000) as client:
            while True:
                try:
                    client.admin.command("ping")
                    break
                except PyMongoError:
                    if time.monotonic() >= deadline:
                        raise SystemExit("Disposable MongoDB did not become ready within 90 seconds")
                    time.sleep(1)
        environment = os.environ.copy()
        environment["MONGO_URI"] = uri
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-m", "integration", "tests/integration"],
            cwd=ROOT, env=environment, check=False).returncode
    finally:
        subprocess.run(["docker", "rm", "--force", container], check=False,
                       stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    sys.exit(main())
