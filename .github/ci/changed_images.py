#!/usr/bin/env python3
"""Select which container images a commit has to build.

Standard CI tool, identical in every repository that builds more than one
image (see AgentContext `ci-conventions`). The per-repository part lives in
`.github/ci/images.json`:

    {
      "rebuild_all": [".github/ci/", ".github/workflows/build.yml", ".dockerignore"],
      "images": [
        {"service": "api", "image": "my-api", "context": ".",
         "dockerfile": "services/api/Dockerfile",
         "inputs": ["services/api/", "services/shared/"]}
      ]
    }

An image is selected when a changed path equals or lies under its Dockerfile,
its `.dockerignore`, or any entry in `inputs`. A change under any `rebuild_all`
entry selects every image. Entries ending in `/` are directories.

Safety rules, so an image is never left stale:
- No usable base revision (first run, force-push, unknown commit, schedule,
  tag, manual run) selects every image.
- `check` mode fails when a Dockerfile COPY/ADD source is not covered by the
  image's inputs, so a new COPY line cannot silently escape change detection.

Usage:
    changed_images.py check
    changed_images.py select [--base REV] [--head REV] [--all]

`select` writes `build_matrix`, `has_build`, `retag` and `has_retag` to
$GITHUB_OUTPUT (when set) and a summary to $GITHUB_STEP_SUMMARY.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path, PurePosixPath

CONFIG = Path(".github/ci/images.json")


def load_config() -> dict:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    for image in config["images"]:
        for key in ("service", "image", "dockerfile"):
            if not image.get(key):
                raise SystemExit(f"{CONFIG}: image entry without {key!r}: {image}")
        image.setdefault("context", ".")
        image.setdefault("inputs", [])
    config.setdefault("rebuild_all", [])
    return config


def norm(path: str) -> str:
    """Repository-relative path. Directories end with '/'; the root is ''."""
    is_dir = path.endswith("/")
    while path.startswith("./"):
        path = path[2:]
    if path in ("", "."):
        return ""
    clean = str(PurePosixPath(path))
    return clean + "/" if is_dir else clean


def covers(entry: str, path: str) -> bool:
    """True when `entry` (a file or directory) contains `path`."""
    entry = norm(entry)
    if entry == "":
        return True
    as_dir = entry if entry.endswith("/") else entry + "/"
    return path == entry.rstrip("/") or path.startswith(as_dir)


def context_dir(image: dict) -> str:
    context = norm(image["context"])
    return "" if context == "" else context.rstrip("/") + "/"


def image_entries(image: dict) -> list[str]:
    return [image["dockerfile"], context_dir(image) + ".dockerignore", *image["inputs"]]


def select(config: dict, paths: list[str]) -> list[dict]:
    paths = [norm(p) for p in paths if p]
    if any(covers(e, p) for e in config["rebuild_all"] for p in paths):
        return list(config["images"])
    return [
        image
        for image in config["images"]
        if any(covers(e, p) for e in image_entries(image) for p in paths)
    ]


def dockerfile_sources(dockerfile: Path) -> list[str]:
    """Context-relative COPY/ADD sources, excluding copies from other stages."""
    text = dockerfile.read_text(encoding="utf-8")
    text = re.sub(r"\\\r?\n", " ", text)  # join continuation lines
    sources: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        match = re.match(r"(?i)^(COPY|ADD)\s+(.*)$", line)
        if not match:
            continue
        rest = match.group(2).strip()
        if rest.startswith("["):
            args = json.loads(rest)
        else:
            args = shlex.split(rest)
        flags = [a for a in args if a.startswith("--")]
        if any(f.startswith("--from") for f in flags):
            continue
        args = [a for a in args if not a.startswith("--")]
        if rest.lstrip().startswith("<<") or len(args) < 2:
            continue  # heredoc or malformed: nothing from the context
        for src in args[:-1]:
            if re.match(r"^[a-z]+://", src):
                continue  # remote ADD
            sources.append(src)
    return sources


def check(config: dict) -> int:
    problems = []
    for image in config["images"]:
        dockerfile = Path(image["dockerfile"])
        if not dockerfile.is_file():
            problems.append(f"{image['service']}: {dockerfile} does not exist")
            continue
        entries = image_entries(image) + config["rebuild_all"]
        for src in dockerfile_sources(dockerfile):
            parts = src.split("/")
            for i, part in enumerate(parts):
                if any(ch in part for ch in "*?["):
                    src = "/".join(parts[:i]) + "/"
                    break
            path = norm(context_dir(image) + src)
            if path and not path.endswith("/") and Path(path).is_dir():
                path += "/"
            if not any(covers(e, path) for e in entries):
                problems.append(
                    f"{image['service']}: {image['dockerfile']} copies '{src}' "
                    f"({path or 'the whole build context'}), which no input "
                    f"in {CONFIG} covers"
                )
    for line in problems:
        print(f"::error file={CONFIG}::{line}")
    if not problems:
        print(f"{CONFIG}: every COPY/ADD source of every image is covered")
    return 1 if problems else 0


def git_has(rev: str) -> bool:
    return (
        subprocess.run(
            ["git", "cat-file", "-e", f"{rev}^{{commit}}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def changed_paths(base: str, head: str) -> list[str] | None:
    if not base or set(base) == {"0"} or not git_has(base) or not git_has(head):
        return None
    out = subprocess.check_output(
        ["git", "diff", "--no-renames", "--name-only", "-z", base, head, "--"]
    )
    return [p for p in out.decode().split("\0") if p]


def emit(selected: list[dict], config: dict, reason: str) -> None:
    unchanged = [i for i in config["images"] if i not in selected]
    matrix = json.dumps({"include": selected}, separators=(",", ":"))
    retag = json.dumps(unchanged, separators=(",", ":"))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write(f"build_matrix={matrix}\n")
            out.write(f"has_build={'true' if selected else 'false'}\n")
            out.write(f"retag={retag}\n")
            out.write(f"has_retag={'true' if unchanged else 'false'}\n")
    lines = [
        "### Image selection",
        "",
        f"Reason: {reason}",
        "",
        "| Image | Action |",
        "|---|---|",
    ]
    lines += [f"| `{i['image']}` | build |" for i in selected]
    lines += [f"| `{i['image']}` | unchanged |" for i in unchanged]
    summary = "\n".join(lines) + "\n"
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as out:
            out.write(summary)
    print(summary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    sel = sub.add_parser("select")
    sel.add_argument("--base", default="")
    sel.add_argument("--head", default="HEAD")
    sel.add_argument("--all", action="store_true")
    args = parser.parse_args()
    config = load_config()
    if args.command == "check":
        return check(config)
    if args.all:
        emit(list(config["images"]), config, "full build requested")
        return 0
    paths = changed_paths(args.base, args.head)
    if paths is None:
        emit(list(config["images"]), config, f"no usable base revision ({args.base or 'none'}); building everything")
        return 0
    emit(select(config, paths), config, f"{len(paths)} changed path(s) since {args.base[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
