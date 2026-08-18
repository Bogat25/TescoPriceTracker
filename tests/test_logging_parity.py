"""
Parity test for the in-repo copies of ``logging_setup.py``.

Each Python service in this stack ships its own copy of the helper so the
service is self-contained at build time (no shared mount, no submodule).
That convenience is only safe if the copies stay byte-identical — the
moment one drifts, services start emitting subtly different JSON shapes
and Vector's transform contract weakens.

This test catches drift the cheapest way possible: by hashing every copy
and asserting they all agree.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_COPIES = [
    REPO_ROOT / "alert-service"        / "logging_setup.py",
    REPO_ROOT / "auth-gateway"         / "logging_setup.py",
    REPO_ROOT / "backend-api"          / "logging_setup.py",
    REPO_ROOT / "scheduler"            / "logging_setup.py",
    REPO_ROOT / "scraper"              / "logging_setup.py",
    REPO_ROOT / "recomendation-system" / "logging_setup.py",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_every_service_has_a_copy():
    missing = [p for p in EXPECTED_COPIES if not p.exists()]
    assert not missing, (
        f"missing logging_setup.py in: {[str(p.parent.name) for p in missing]}. "
        "Roll the canonical copy from alert-service into the missing service "
        "(see tests/README.md or docs/logging.md)."
    )


def test_all_copies_are_byte_identical():
    hashes = {p.parent.name: _sha256(p) for p in EXPECTED_COPIES}
    distinct = set(hashes.values())
    assert len(distinct) == 1, (
        "logging_setup.py copies have drifted. Per-service hashes:\n  "
        + "\n  ".join(f"{svc}: {h}" for svc, h in hashes.items())
        + "\nFix by copying alert-service/logging_setup.py into the others."
    )
