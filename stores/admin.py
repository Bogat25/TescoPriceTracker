"""Switch stores on or off without a redeploy.

Run inside the ``api`` container, e.g. from Portainer's console::

    python -m stores.admin list
    python -m stores.admin set auchan enabled=false
    python -m stores.admin set tesco scrape_enabled=true loyalty_enabled=false

It also rebuilds the cross-store category mapping, which the daily scrapes do
on their own::

    python -m stores.admin categories

Changes reach every service within the registry cache time (60 s). There is no
HTTP endpoint for this on purpose: the public gateway forwards ``/api/v1``.
"""

import argparse
import json
import sys

from stores.registry import FLAG_FIELDS, UnknownStore, registry


def _parse_flag(assignment: str) -> tuple:
    name, sep, value = assignment.partition("=")
    if not sep or name not in FLAG_FIELDS or value.lower() not in ("true", "false"):
        raise argparse.ArgumentTypeError(f"expected one of {FLAG_FIELDS} as name=true|false, got {assignment!r}")
    return name, value.lower() == "true"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m stores.admin", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="show every store and its switches")
    commands.add_parser("categories", help="rebuild the cross-store category mapping")
    set_parser = commands.add_parser("set", help="change switches of one store")
    set_parser.add_argument("store")
    set_parser.add_argument("flags", nargs="+", type=_parse_flag)
    args = parser.parse_args(argv)

    registry.seed()
    if args.command == "categories":
        from stores import categories
        print(json.dumps(categories.rebuild(), indent=2, ensure_ascii=False))
        return 0
    if args.command == "set":
        try:
            registry.set_flags(args.store, **dict(args.flags))
        except UnknownStore:
            print(f"unknown store: {args.store}", file=sys.stderr)
            return 2
    for store in registry.all():
        print(json.dumps({"id": store.id, **{flag: getattr(store, flag) for flag in FLAG_FIELDS}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
