# The gates, and the same commands the pipeline runs.
#
# `lint` runs both halves because Infra's scripts/python-quality.sh does. A `make lint` that
# checked only the first would be green here and red in CI, which is the one thing a local
# gate must never be.
.PHONY: check lint format test

check: lint test

lint:
	./.venv/bin/ruff check .
	./.venv/bin/ruff format --check .

format:
	./.venv/bin/ruff format .

# The suite runs against the seeded database. REQUIRE_DB=1 turns an absent one from skips into
# failures, which is what the pipeline sets (README § Testing).
test:
	./.venv/bin/python -m pytest
