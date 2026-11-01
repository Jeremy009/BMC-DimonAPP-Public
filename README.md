> This is a curated view of the real production app: its history is removed and names, infrastructure identifiers and the live address are left out. It is shared for viewing only; see `LICENSE`.

# DimonAPP

Worker administration and Dimona declarations for Brussels Monkeys Climbing ASBL (BMC), a climbing association in Brussels. Workers declare the activities they perform at the gym; the application checks that they may, declares them to the RSZ/ONSS (Belgian social security) and prepares their pay and their yearly tax fiche. Admins can also ask Claude about the activities through a read-only MCP server that never shows the model any personal data. The interface is in French.

It runs in production for BMC, version 3.1.0, on Google Cloud.

![Admin dashboard](docs/screenshots/04-admin-dashboard.png)

| Login | Declaring an activity (worker) |
|---|---|
| ![Login](docs/screenshots/01-login.png) | ![Declaring an activity](docs/screenshots/02-worker-declare.png) |
| **Monthly overview (worker)** | **Monthly report and payment export (admin)** |
| ![Monthly overview](docs/screenshots/03-worker-overview.png) | ![Monthly report](docs/screenshots/05-admin-report.png) |
| **Activities (admin)** | **Workers (admin)** |
| ![Activities](docs/screenshots/06-admin-activities.png) | ![Workers](docs/screenshots/07-admin-workers.png) |

The screenshots use fictional demo data in the `TEST` environment; `tools/screenshots/take-screenshots.sh` regenerates them (uv and Docker needed).

## What it does

- **Timesheets.** Workers declare their activities; admins see the monthly totals and produce the monthly payment file (SEPA pain.001, validated against its XSD).
- **Authorisations.** An activity is only accepted with a valid contract and a valid qualification on file.
- **Dimona.** Article 17 workers and flexi-jobbers are declared to the RSZ the moment they declare an activity, through the official REST service.
- **Legal limits.** The admin dashboard warns when a worker nears a yearly or quarterly limit; it never blocks a declaration.
- **Fiche 281.27.** At year end, the fiscal fiches as PDF and as Belcotax-on-web XML.
- **MCP server.** Admins can ask Claude about the activities, without any personal data leaving the database ([below](#mcp-server)).

Workers sign in with Google or with a username and password an admin gave them; admins sign in with Google only.

## Engineering highlights

A small organisation's legal declarations, payroll inputs and tax documents, handled by one application in production. What it shows:

- **Specification first, traced to the end.** `docs/FDS.md` is a full functional design specification with about 170 numbered requirements (R1.1 to R20.23) and a change log of every revision. `docs/TRACEABILITY.md` maps each requirement to the code that implements it and the test or manual check that proves it.
- **Integration with a government API.** The Dimona client follows the official RSZ OpenAPI specification: OAuth2 client credentials with a signed-JWT client assertion (RS256), token reuse, a strict 2-minute limit, and a rule that the application never assumes an outcome: what it stores is the RSZ's real answer or "pending".
- **Belgian payroll and tax rules as plain, tested Python.** Worker types (article 17, flexi-job, freelancer, volunteer), a one-way status ladder, versioned compensation sheets, quarterly and yearly legal limits, the SEPA payment file and the Belcotax XML of the fiche 281.27. Business rules live in small functions apart from the Streamlit pages, so they are tested without a UI.
- **Privacy by design for AI access.** The MCP server lets an AI assistant answer questions about the activities while no name, identifier, amount or free text ever reaches the model, enforced in four independent layers: database role and views, typed tool outputs, infrastructure, tests ([details](#privacy)).
- **Tested against real infrastructure.** About 850 tests with pytest. Database tests run against a real PostgreSQL in Docker (testcontainers), including privilege tests for the read-only role and a leak test that calls every MCP tool on seeded data and looks for every personal value.
- **Production cloud set-up.** One Docker image for three environments (local test, acceptance on the RSZ test service, production). On Google Cloud: Cloud Run, Cloud SQL with IAM database sign-in, Cloud Storage, Secret Manager, a service account per service with IAM conditions so acceptance can never reach production. Every command is written down in `docs/DEPLOYMENT.md`.
- **AI-assisted engineering with human ownership.** The code was written with Claude Code under strict rules in `CLAUDE.md`: Python style, security rules, a branch and a pull request per unit of work, version raised once per pull request, lint and tests green. The specification, the design decisions and the review of every pull request stay with the maintainer.

## Stack

Python managed with uv, Streamlit, SQLAlchemy 2.0 with psycopg 3, Alembic, PostgreSQL, Pydantic, pytest with testcontainers, Ruff. One Docker image runs in every environment: in GCP on Cloud Run, with Cloud SQL, Cloud Storage and Secret Manager in `europe-west1`. The MCP server uses the standalone [fastmcp](https://gofastmcp.com) package.

## Environments

`APP_ENV` names the environment. It decides only the Dimona service, the label in the sidebar and whether the MCP server may run without sign-in; everything else is injected configuration.

| `APP_ENV` | Runs | Dimona | Data |
|---|---|---|---|
| `TEST` | Locally (`make run`), never in GCP | No call: a fake service answers. `FAKE_DIMONA_OUTCOME` is `accept` (default), `reject` or `timeout` | Fake (`make seed`) |
| `ACC` | Cloud Run services `dimonapp-acc` and `dimonapp-mcp-acc` | The RSZ test service. Needs the `DIMONA_*` values and the private key (see `.env.example`), kept in a folder outside the repository | Fictitious workers the RSZ test service knows |
| `PROD` | Cloud Run services `dimonapp-prod` and `dimonapp-mcp-prod`. Never set locally | The live RSZ service | The real data |

The log names the Dimona service in use when a worker first opens the application.

## MCP server

An admin can ask an AI assistant such as Claude about the declared activities: how many hours were declared this week, whether every weekday had a declaration, which activities need a look, whether the current month looks correct. The MCP server answers through a fixed set of read-only tools. MCP, the Model Context Protocol, is the open standard through which an AI assistant calls the tools of a server. It runs as a second Cloud Run service next to the application, from the same image (FDS section 15).

Below, Claude is connected to the server in acceptance, signed in as an active admin, on fictitious data. The admin asks which days had work in the last two weeks, then for the anomalies of the month. Only dates, hours, activity types, worker types and Dimona statuses come back (sped up twice).

![Claude asks the DimonAPP MCP server of acceptance for the daily activities of two weeks and the anomalies of October](docs/media/mcp-demo.gif)

### Tools

| Tool | Answers |
|---|---|
| `summarise_period(start, end)` | Counted hours and activities per activity type and worker type, distinct workers, cancelled, rejected and pending declarations |
| `list_daily_activities(start, end)` | Every day of the period, with its activities, empty days included |
| `find_anomalies(start, end)` | Pending or rejected Dimona, cancellations, long activities and days, many days in one week, flexi-jobs under the minimum, missing limits, workers near a legal limit |
| `review_month(year, month)` | The summary, the empty days and the anomalies of one month |

There is also a resource with the catalogue of activity types and a prompt for the monthly review, which asks the model to answer in French.

### Privacy

**No personal data, no direct identifiers, and no pay or banking data leaves the database or is exposed to the model.** The tools return hours, counts, dates, activity types, worker types, Dimona statuses and activity ids; never a name, e-mail address, national register number, IBAN, address or worker id, never an amount in euro, never free text. Anything that needs a follow-up comes back as an activity id and a date, which the admin opens in the application.

**The limit of the guarantee.** Aggregates are not anonymous in an organisation this small: "the only flexi-jobber worked on Tuesday" points to one person. The guarantee is about identifiers and sensitive attributes, not anonymity. For the same reason there is no question about one person.

The rule is enforced in four layers, so a mistake in one of them does not leak:

1. **Database.** The service signs in as a role of its own that can read a few purpose-built views and nothing else: no table, no euro column, no free text. Limits in euro are compared inside the database, which returns only how many workers are near a limit. Whether an e-mail is an active admin is asked of a function, without reading the admins table.
2. **Code.** Curated tools whose typed outputs have no field for any of the data above; no free-form query, no write action.
3. **Infrastructure.** The service runs as a service account of its own that cannot reach the application's secrets, the documents, the Dimona key or the database of another environment.
4. **Tests.** A leak test calls every tool, resource and prompt on seeded data and looks for every name, identifier, address and amount; a privilege test checks that the role is refused on every table; sign-in tests check that only an active admin gets in.

### Access

- `/public/mcp` needs no sign-in and only says what the server is.
- `/mcp` needs Google sign-in, through FastMCP's OAuth proxy, and lets in only an e-mail that is an active admin of the application; every other account is refused, a Google worker account included.
- In acceptance and production the service refuses to start without sign-in. Locally it may run without sign-in, on the fake data only, and then refuses to start unless it listens on the developer's machine alone (a loopback address, never in Cloud Run), and refuses any request not addressed to that machine.
- An unexpected error reaches the MCP client without its details; only the messages the tools give on purpose, such as a refused period, get through.

To connect from Claude: Settings, Connectors, Add custom connector, with the address of `/mcp` (`docs/DEPLOYMENT.md`, section 7).

## Local development

1. Install uv and Docker.
2. Copy `.env.example` to `.env` (never commit `.env`).
3. `make db` starts the local PostgreSQL, `make migrate` applies the database migrations.
4. `make seed` fills the local database with fake data. Set `SEED_PASSWORD` in `.env` first to sign in as a fake local worker (`camille`, `noor`, `robin`, `alex`), and `SEED_ADMIN_EMAIL` to sign in as admin with your own Google account.
5. `make run` starts the app, `make test` runs the tests (Docker must be running), `make lint` runs Ruff.

Good to know:

- **Google sign-in** needs the four Google variables of `.env.example`; without them the Google button is disabled and only the username and password form works.
- **Uploaded documents** go to the folder named by `STORAGE_FOLDER` (default `local_storage`, git-ignored); in GCP to the Cloud Storage bucket named by `STORAGE_BUCKET`.
- **The RSZ test service:** `make test-rsz` declares and cancels one activity there, as `ACC`. It lives in `tests/integration/` and is never part of `make test`.
- **The MCP server:** after `make migrate`, `make mcp-user` creates its database user; with `MCP_DATABASE_URL` of `.env.example`, `make mcp` serves `http://127.0.0.1:8081/mcp` without sign-in, on the fake local data only. Add it to Claude Code with `claude mcp add --transport http dimonapp http://127.0.0.1:8081/mcp`.

## Deployment to GCP

Acceptance and production live in one GCP project (`<project-id>` below), region `europe-west1`. The commands to set up an environment, the checks after a first deployment and the day-to-day tasks are in `docs/DEPLOYMENT.md`.

- **One image.** Cloud Build builds the `Dockerfile` from `main` and tags it with the version of `src/dimonapp/__init__.py`. The same image goes to acceptance first and to production after acceptance passed.
- **Per environment, nothing shared.** Each has its own Cloud Run service (at most one instance, public HTTPS, the application handles the sign-in), Cloud SQL PostgreSQL instance (nightly backups; production adds point-in-time recovery and deletion protection), private bucket `dimonapp-<env>-documents`, service account `dimonapp-<env>`, which may use only the Cloud SQL instance of its environment, and Google OAuth client. The MCP service has its own service account, secrets, OAuth client and bucket. Nothing is copied from one environment to the other.
- **Configuration.** Plain values (environment name, bucket, redirect address, Google client ID, RSZ identifiers, first admin) are set on the service at deploy time. Secrets (database URL, sign-in secrets, RSZ private key and its passphrase) come from Secret Manager as `dimonapp-<env>-...`, readable only by the service account of that environment.
- **Database.** The container applies the Alembic migrations when it starts, so a release migrates acceptance before it reaches production. The first admin comes from `FIRST_ADMIN_EMAIL`.

### Releasing a new version

Once the pull request of the version is merged, from the root of the repository. Sign in first with `gcloud auth login` when the last sign-in is some hours old.

1. Take the merged code and name the image after its version:

   ```bash
   git switch main && git pull
   export VERSION=$(uv run python -c "import dimonapp; print(dimonapp.__version__)")
   export IMAGE="europe-west1-docker.pkg.dev/<project-id>/dimonapp/dimonapp:$VERSION"
   ```

2. Build the image, once per version (about three minutes):

   ```bash
   gcloud builds submit --tag "$IMAGE" --project=<project-id>
   ```

3. Update acceptance. Only the image changes; settings, secrets and data stay, and the migrations run when the new container starts:

   ```bash
   export ENV=acc
   gcloud run services update "dimonapp-$ENV" --project=<project-id> --region=europe-west1 --image="$IMAGE"
   ```

   Update the MCP service of the environment with the same image (`docs/DEPLOYMENT.md`, section 7):

   ```bash
   gcloud run services update "dimonapp-mcp-$ENV" --project=<project-id> --region=europe-west1 --image="$IMAGE"
   ```

4. Check it: the first command prints the image that runs, the second the start-up log (migrations applied, Streamlit started, no error). Then open the application and read the version in the footer.

   ```bash
   gcloud run services describe "dimonapp-$ENV" --project=<project-id> --region=europe-west1 --format='value(spec.template.spec.containers[0].image)'
   gcloud run services logs read "dimonapp-$ENV" --project=<project-id> --region=europe-west1 --limit=30
   ```

5. Test in acceptance. When it passes, repeat steps 3 and 4 with `export ENV=prod`: the same image, no new build.

To go back, run step 3 with the tag of the previous version. That does not undo a migration, so check the pull requests in between first.

### Adding an admin

The application has no screen to manage admins: an admin is a row in the `admins` table of the environment, holding the Google address the person signs in with. `FIRST_ADMIN_EMAIL` creates the first one only, while the table is still empty.

In acceptance or production:

1. In the Google Cloud console open Cloud SQL, the instance `dimonapp-<env>` (`dimonapp-acc` or `dimonapp-prod`), then "Cloud SQL Studio".
2. Sign in to the database `dimonapp` as user `dimonapp`. The password is part of the database URL kept in Secret Manager, between `dimonapp:` and `@`:

   ```bash
   gcloud secrets versions access latest --secret=dimonapp-<env>-database-url --project=<project-id>
   ```

3. Add the address, in lower case:

   ```sql
   INSERT INTO admins (email) VALUES ('name@example.com');
   ```

The new admin signs in with the Google button straight away; nothing needs to be deployed. Locally the same statement goes through the database container:

```bash
docker compose exec db psql -U dimonapp -d dimonapp -c "INSERT INTO admins (email) VALUES ('name@example.com');"
```

- An address that is in both tables, admins and workers, signs in as admin.
- To take the access away, deactivate the row instead of deleting it: `UPDATE admins SET is_active = false WHERE email = 'name@example.com';`. A deactivated admin is refused at sign-in.

## Repository layout

| Path | What it is |
|---|---|
| `src/dimonapp/` | The application, the MCP server and the Alembic migrations |
| `tests/` | The test suite; `tests/integration/` holds the optional call to the RSZ test service |
| `docs/FDS.md` | Functional Design Specification, the source of truth |
| `docs/TRACEABILITY.md` | Every requirement mapped to its code and tests |
| `docs/DEPLOYMENT.md` | The exact commands to set up and update acceptance and production in GCP |
| `docs/openapi_dimona_v2.yaml` | Official RSZ specification of the Dimona REST service |
| `docs/media/` | The recording of the MCP server above |
| `docs/screenshots/`, `tools/screenshots/` | README screenshots and the script that regenerates them with fake data |
| `src/dimonapp/assets/` | The two logos, `favicon.png` and `logoarriere.png`, and the resized copies of the favicon |
| `CLAUDE.md` | Instructions Claude Code reads automatically: stack, commands, rules |
| `.env.example` | Template for the local, git-ignored `.env` |

## Way of working

Each feature, fix or requirement is built on its own branch and reviewed before it reaches `main`:

1. Claude Code creates a branch named `claude/<feature>`.
2. It implements the work following the Python style in `CLAUDE.md`.
3. It raises the version in `src/dimonapp/__init__.py`, once per pull request.
4. It runs Ruff (line length 100) and the full test suite; both must be clean.
5. It opens a pull request listing the version and the requirement IDs covered.
6. It stops and asks for review. Only the maintainer merges; nothing is pushed directly to `main`.
