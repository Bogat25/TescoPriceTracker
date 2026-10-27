# Linux development: TescoPriceTracker

This checkout uses the shared Linux runner from the sibling `AgentContext`
repository. Clone it beside this repository, or set `ARKPLUS_LINUX_RUNNER` to
its `scripts/linux_workspace.py`. The profile is checked in as `linux.json`.

```bash
bash ../AgentContext/scripts/bootstrap_linux.sh
make setup
make lint
make test
make build
```

`make check` runs setup, lint, tests and build. `make doctor` checks tools.
Python uses an isolated `.venv-linux` with Python 3.12; Node projects use their
committed lockfiles with `npm ci`. Build outputs go to `.artifacts` or the
framework's normal ignored output directory. Existing production `.env` files
must not be used for automated tests. Production credentials are removed from
the runner's child environment. No command publishes images, pushes Git, or
deploys services.

`make images` builds local Docker images without publishing them. Docker Engine
and a working local daemon must be installed separately by an administrator.
`make integration` is explicit and can require disposable databases/containers;
read the repository's existing test documentation before running it.

Run all sibling profiles and collect a report:

```bash
python3 ../AgentContext/scripts/linux_workspace.py --all \
  --report /tmp/linux-workspace.md check
```

See `AgentContext/docs/linux-workspace.md` for system prerequisites, scope and
known host limitations. A blocked prerequisite is reported separately from a
failed check; it must not be interpreted as a successful build or test.

`make integration` creates a temporary MongoDB 8 container with a random
loopback port, runs the two-store suite and removes that container on exit.
It overrides `MONGO_URI` for the tests and uses no existing database.
