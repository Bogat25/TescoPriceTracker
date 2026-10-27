.PHONY: help setup lint test build integration images doctor check
help:
	@printf "Linux workspace targets: setup lint test build integration images doctor check\nSee LINUX.md.\n"
setup lint test build integration images doctor check:
	@bash scripts/linux.sh $@
