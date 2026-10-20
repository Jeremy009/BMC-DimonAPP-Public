.PHONY: test test-rsz run lint db migrate seed docker-build

# Run the full test suite (Docker must be running for the database tests).
test:
	uv run pytest

# Optional: declare, update and cancel activities at the RSZ test service, as the ACC
# environment with the DIMONA_* settings of .env. The .env is also loaded into the
# environment, where the test reads RSZ_TEST_NATIONAL_REGISTER_NUMBER; APP_ENV=ACC still wins.
# Never part of `make test`; see tests/integration/test_rsz_dimona_live.py.
test-rsz:
	APP_ENV=ACC RSZ_INTEGRATION=1 uv run --env-file .env pytest tests/integration

# Start the application locally with the settings from .env.
# The Streamlit secrets file for Google sign-in is written from .env first (R4.10), and the
# served page is made French for every browser, as in the Docker image (R18.1).
run:
	uv run python -m dimonapp.secrets_file
	uv run python -m dimonapp.page_locale
	uv run streamlit run src/dimonapp/app.py

# Format and lint the code with Ruff.
lint:
	uv run ruff format
	uv run ruff check --fix

# Start the local throwaway PostgreSQL.
db:
	docker compose up -d db

# Apply the database migrations to the database of .env.
migrate:
	uv run alembic upgrade head

# Fill the local throwaway database with fake data (never real data, R3.7).
seed:
	uv run python -m dimonapp.fake_data

# Build the Docker image used for every environment.
docker-build:
	docker build -t dimonapp .
