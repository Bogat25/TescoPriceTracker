"""
Verify every entrypoint that calls ``setup_logging()`` can actually resolve
``logging_setup`` from its working directory under container conditions.

Why this exists
---------------
A real bug from the Chunk C rollout: ``alert-service/jobs/keycloak_sync.py``
runs with ``working_dir: /app/alert-service`` and command
``python jobs/keycloak_sync.py``. Python adds the **script's** directory
(``jobs/``) to sys.path — NOT the working dir. So ``from logging_setup
import …`` would fail at boot even though ``logging_setup.py`` lives one
level up. That class of bug doesn't show up in unit tests of the helper
itself; we need a per-entrypoint import-resolution test.

Strategy
--------
For each entrypoint we know about, simulate the container conditions:
  * ``cwd`` = the working_dir
  * ``sys.path`` = `[script-dir, *PYTHONPATH split, ...]`
Then exec just the import lines of the entrypoint in a subprocess and
assert it doesn't raise.

We don't actually run the full module (it would try to connect to Mongo
etc.); we extract its import block at the top of the file via a regex
and run only that.
"""
from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# (entrypoint_path, container_working_dir, command_arg_path)
# These mirror docker-compose.override.yml exactly. Update if compose changes.
ENTRYPOINTS = [
    ("auth-gateway/app.py",                 "/app/auth-gateway",         "app.py"),
    ("backend-api/app.py",                  "/app/backend-api",          "app.py"),
    ("alert-service/app.py",                "/app/alert-service",        "app.py"),
    ("alert-service/jobs/keycloak_sync.py", "/app/alert-service",        "jobs/keycloak_sync.py"),
    ("recomendation-system/app.py",         "/app/recomendation-system", "app.py"),
    ("scheduler/scheduler.py",              "/app/scheduler",            "scheduler.py"),
]


def _extract_imports(path: Path) -> str:
    """Pull the leading import block from a file: everything before the first
    non-import, non-comment, non-blank statement we can't safely run
    standalone (function/class/assignment).

    Handles multi-line `from x import (a, b, c)` continuations by tracking
    parenthesis depth across lines.

    Also strips the leading `import logging_setup` line via simple call
    sites — but we keep them: the whole point of this test is that THOSE
    imports resolve under container conditions.
    """
    text = path.read_text(encoding="utf-8")
    out_lines: list[str] = []
    in_docstring = False
    docstring_quote: str | None = None
    paren_depth = 0  # tracks unclosed ( or [ inside imports

    for line in text.splitlines():
        stripped = line.lstrip()

        # Allow leading module docstrings (single- or triple-quoted).
        if not in_docstring and stripped.startswith(('"""', "'''")):
            quote = stripped[:3]
            rest = stripped[3:]
            if rest.endswith(quote) and len(rest) >= 3:
                out_lines.append(line)
                continue
            in_docstring = True
            docstring_quote = quote
            out_lines.append(line)
            continue
        if in_docstring:
            out_lines.append(line)
            if docstring_quote and docstring_quote in stripped:
                in_docstring = False
                docstring_quote = None
            continue

        # If we're inside a multi-line `from x import (...)`, keep collecting
        # until parens balance.
        if paren_depth > 0:
            out_lines.append(line)
            paren_depth += line.count("(") + line.count("[")
            paren_depth -= line.count(")") + line.count("]")
            continue

        # Blank / comment / import line: keep, and update paren tracking.
        if (stripped == ""
                or stripped.startswith("#")
                or stripped.startswith("import ")
                or stripped.startswith("from ")):
            out_lines.append(line)
            paren_depth += line.count("(") + line.count("[")
            paren_depth -= line.count(")") + line.count("]")
            continue

        # First "real" code line — stop. We don't execute beyond this.
        break

    return "\n".join(out_lines)


@pytest.mark.parametrize("rel_path,working_dir,cmd_arg", ENTRYPOINTS)
def test_entrypoint_import_block_resolves_under_container_conditions(
    tmp_path, rel_path, working_dir, cmd_arg,
):
    """
    Stage the repo into a tmp tree mirroring /app, then run a subprocess
    that imitates the container's invocation. If any `import` line fails
    (because logging_setup is unreachable from the script's dir), the
    subprocess exits non-zero and the test fails with the real error.
    """
    # Mirror /app/<service>/* into tmp_path. We shallow-link the repo by
    # copying just the service folder plus any sibling modules it imports.
    # Rather than guess which siblings, we copy the whole service folder —
    # cheap, and keeps the test robust as the codebase grows.
    service_root = REPO_ROOT / rel_path.split("/")[0]
    staged_app = tmp_path / "app"
    staged_app.mkdir()
    staged_service = staged_app / service_root.name

    # Use shutil.copytree but skip __pycache__ to keep this fast.
    import shutil
    shutil.copytree(
        service_root, staged_service,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests"),
    )

    # Stub out third-party deps the import block may pull in. We don't
    # install them in CI; instead we generate empty stand-ins on a temp
    # PYTHONPATH so `import pycron` etc. just succeed.
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for stub in [
        "pycron", "pytz", "httpx", "fastapi", "fastapi.middleware",
        "fastapi.middleware.cors", "fastapi.responses", "structlog",
        "structlog.contextvars", "structlog.processors", "structlog.stdlib",
        "cryptography", "cryptography.fernet",
        "motor", "motor.motor_asyncio",
        "pymongo", "qdrant_client", "qdrant_client.models",
        "uvicorn", "resend", "jinja2",
        # Local packages that may not be present in the staged copy
            "mongo", "mongo.database_manager", "mongo.stats_manager",
            "mongo.queries", "mongo.products_catalog_manager", "config",
        "recommendation_engine", "data_preparation",
        "scraper", "scraper.scraper",
        "services", "services.keycloak_admin", "services.user_repo",
        "auth", "routers", "routers.alerts", "routers.health",
        "routers.internal", "models", "db",
        # structlog-specific bits we need to attribute-access
    ]:
        parts = stub.split(".")
        d = stubs
        for p in parts[:-1]:
            d = d / p
            d.mkdir(exist_ok=True)
            (d / "__init__.py").write_text("")
        (d / f"{parts[-1]}.py").write_text(
            "import sys\n"
            "class _Anything:\n"
            "    def __getattr__(self, name): return _Anything()\n"
            "    def __call__(self, *a, **kw): return _Anything()\n"
            "    def __iter__(self): return iter([])\n"
            "sys.modules[__name__] = _Anything()\n"
        )

    # Build the runner: cd into working_dir, prepend stubs to PYTHONPATH,
    # then exec the import block.
    container_wd = staged_app / Path(working_dir).name
    import_block = _extract_imports(REPO_ROOT / rel_path)

    runner = textwrap.dedent(f"""
        import os, sys
        os.chdir({str(container_wd)!r})
        # Mimic Python's behaviour: script-dir on path[0]
        script_dir = os.path.dirname({str(container_wd / cmd_arg)!r})
        sys.path.insert(0, script_dir)
        # Mimic compose env: PYTHONPATH=/app
        sys.path.insert(0, {str(staged_app)!r})
        # Test stubs come last so real modules win where they exist
        sys.path.append({str(stubs)!r})
        # Now the actual import block from the entrypoint:
    """) + "\n" + import_block

    runner_path = tmp_path / "runner.py"
    runner_path.write_text(runner, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(runner_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"Import block of {rel_path} fails under container conditions:\n"
        f"working_dir={working_dir} command=python {cmd_arg}\n"
        f"STDERR:\n{result.stderr}"
    )
