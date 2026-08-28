# The gates, and the same commands .github/workflows/ci.yml runs.
#
# `lint` runs both halves: one that checked only `ruff check` would pass a tree that
# `ruff format --check` fails.
.PHONY: check lint format test

check: lint test

lint:
	./.venv/bin/ruff check .
	./.venv/bin/ruff format --check .

format:
	./.venv/bin/ruff format .

# The suite runs against the seeded database. REQUIRE_DB=1 turns an absent one from skips into
# failures (README § Testing).
test:
	./.venv/bin/python -m pytest
