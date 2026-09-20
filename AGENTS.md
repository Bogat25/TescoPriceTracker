<!-- agent-context:kernel:start sha=47d012fe5e1a9714ad2854b41669f83f177ab11ac16e41048c14ad5eea875afd -->
# User repository preferences

- Create commits locally when requested or when completing repository changes.
- Never push commits, create or modify pull requests, trigger GitHub workflows,
  publish releases, or otherwise write to GitHub.
- Treat all GitHub access as read-only unless the user explicitly revokes this
  rule in a later message.
- Commit directly on each repository's default branch (`main`, or `master` where applicable); do not create feature branches.
- Never add `Co-Authored-By` trailers or any AI attribution lines/footers to commits, PRs, files, or documentation.
- Keep commits few per feature (1-2 clean conventional commits); squash or amend unpushed fixups.
- Never read, print, echo, substring, or output plaintext secret values or token fragments anywhere. Test existence only (`Test-Path Env:NAME` or `[bool]$env:NAME`).
- Maintain strict isolation between AI agents (`codex`, `claude`, `gemini`): separate service accounts, tokens, and endpoints.
<!-- agent-context:kernel:end -->

## This repository
<!-- Tier 1 repo contract (build/test/deploy, idioms) goes here -->
