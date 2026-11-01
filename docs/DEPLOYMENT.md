# Deployment to Google Cloud Platform

How to set up and update the two environments of DimonAPP that run in GCP (FDS 3.2): acceptance and production. The test environment is not deployed: it is the application run locally with `make run` (see `README.md`). Every command is meant to be copied; run them from the root of the repository.

> **Status (01/11/2026):** both environments were set up with these commands in the GCP project of BMC. Acceptance runs with version 3.0.0b14, and its MCP service (section 7) since 3.1.0a2. Production runs with version 3.1.0, and its MCP service as well.

## What gets created

One GCP project holds both environments. Per environment (`acc`, `prod`):

| Resource | Name | Notes |
|---|---|---|
| Cloud Run service | `dimonapp-<env>` | Public HTTPS, at most one instance (R1.7, R1.12) |
| Cloud SQL for PostgreSQL 16 | `dimonapp-<env>` | Own instance, automated backups, no authorised networks (R3.1 to R3.4) |
| Cloud Storage bucket | `dimonapp-<env>-documents` | Private, uploaded contracts and qualifications (R3.6) |
| Service account | `dimonapp-<env>` | The identity of the Cloud Run service; uses only the Cloud SQL instance of its environment |
| Secret Manager secrets | `dimonapp-<env>-...` | Database URL, sign-in secrets, Dimona key (R2.6) |
| Google OAuth client | `DimonAPP <env>` | Its own redirect URI |
| Cloud Run service | `dimonapp-mcp-<env>` | The MCP server, same image, at most one instance (section 7) |
| Service account | `dimonapp-mcp-<env>` | The identity of the MCP service; no access to the application's secrets or bucket |
| Secret Manager secrets | `dimonapp-mcp-<env>-...` | The MCP service's own: its Google client secret and signing key (R20.9) |
| Cloud Storage bucket | `dimonapp-mcp-<env>-oauth` | Private, the encrypted sign-in state of the MCP service (FDS 15.3) |
| Google OAuth client | `DimonAPP MCP <env>` | The MCP service's own, redirect URI `/auth/callback` |

Shared by the two: the project, one Artifact Registry repository, the OAuth consent screen and the Docker image (the same image runs everywhere, R1.6). Everything lives in `europe-west1` (R3.2).

The environments differ only in their name and in injected values (R2.2):

| | acc | prod |
|---|---|---|
| `APP_ENV` | `ACC` | `PROD` |
| Dimona | RSZ test service | live RSZ service |
| Data | fictitious workers the RSZ test service knows | the real data |
| Database extras | none | point-in-time recovery, deletion protection |

Nothing is copied from one environment to the other.

## Before you start

1. Install the Google Cloud CLI (`brew install --cask google-cloud-sdk`) and sign in: `gcloud auth login`. The sign-in of a Workspace account expires after some hours; a command that then fails with "Reauthentication failed" only needs `gcloud auth login` again.
2. Create a GCP project in the BMC organisation with billing enabled, or pick an existing one.
3. Have the RSZ values at hand: client id, enterprise number, employer number and the private key file. The key stays in its folder outside the repository; it is only ever read by the `gcloud secrets` command below.

## 1. Once per project

```bash
export PROJECT_ID=<your-project-id>
export REGION=europe-west1

gcloud config set project "$PROJECT_ID"
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  storage.googleapis.com

gcloud artifacts repositories create dimonapp \
  --repository-format=docker \
  --location="$REGION" \
  --description="DimonAPP images"
```

### OAuth consent screen (once, in the console)

Google sign-in needs a consent screen: console, "Google Auth Platform", "Branding". Choose audience **Internal** when every admin and every Google worker has a BMC Workspace address (FDS section 2); the application then needs no verification by Google. Application name "DimonAPP", support e-mail of BMC.

## 2. Build the image (for every release)

The version is the one of `src/dimonapp/__init__.py`; the image is tagged with it so it is clear what runs where.

```bash
export VERSION=$(uv run python -c "import dimonapp; print(dimonapp.__version__)")
export IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/dimonapp/dimonapp:$VERSION"

gcloud builds submit --tag "$IMAGE"
```

Cloud Build uploads the folder without what `.gitignore` lists, so `.env` and `local_storage/` never leave your machine, and builds the `Dockerfile` for the processor Cloud Run uses. Build from an up-to-date `main`.

The upload lands in a bucket Cloud Build creates itself, `<project>_cloudbuild`, in the US multi-region. It holds source code only, never data.

## 3. Create an environment

Run this section twice: first `acc`, then `prod`. Set the two names first.

```bash
export ENV=acc           # acc or prod
export APP_ENV=ACC       # ACC or PROD (the same environment, in capitals)

export PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
export SERVICE="dimonapp-$ENV"
export SQL_INSTANCE="dimonapp-$ENV"
export BUCKET="dimonapp-$ENV-documents"
export SERVICE_ACCOUNT="dimonapp-$ENV@$PROJECT_ID.iam.gserviceaccount.com"
export SERVICE_URL="https://$SERVICE-$PROJECT_NUMBER.$REGION.run.app"
export SQL_CONDITION="resource.name == 'projects/$PROJECT_ID/instances/$SQL_INSTANCE' && resource.type == 'sqladmin.googleapis.com/Instance'"
echo "$SERVICE_URL"
```

`SERVICE_URL` is the address of the application. It is known before the first deployment, which the Google sign-in needs (step 3.5). Always use this address, not the second, older one Cloud Run also shows. `SQL_CONDITION` limits a role of a service account to the Cloud SQL instance of this environment (sections 3.3 and 7.1).

### 3.1 Database (R3.1 to R3.4)

```bash
gcloud sql instances create "$SQL_INSTANCE" \
  --database-version=POSTGRES_16 \
  --edition=enterprise \
  --tier=db-f1-micro \
  --region="$REGION" \
  --storage-size=10 \
  --storage-auto-increase \
  --backup-start-time=02:00 \
  --backup-location="$REGION"

gcloud sql databases create dimonapp --instance="$SQL_INSTANCE"

export DB_PASSWORD=$(openssl rand -hex 24)
gcloud sql users create dimonapp --instance="$SQL_INSTANCE" --password="$DB_PASSWORD"
```

- Creating the instance takes several minutes.
- Backups run every night and stay in `europe-west1` (R3.2, R3.4), in acceptance too: its data is fictitious, but the cost is negligible and a restore can be tried there first. For production add `--enable-point-in-time-recovery --deletion-protection` to the first command.
- No network is authorised, so the database cannot be reached from the internet; only Cloud Run's built-in connection gets in (R3.3). Do not add an authorised network later.
- `db-f1-micro` is the smallest machine and is enough for BMC; change the tier later with `gcloud sql instances patch` if needed.

### 3.2 Document bucket (R3.6)

```bash
gcloud storage buckets create "gs://$BUCKET" \
  --location="$REGION" \
  --uniform-bucket-level-access \
  --public-access-prevention
```

### 3.3 Service account

```bash
gcloud iam service-accounts create "dimonapp-$ENV" --display-name="DimonAPP $APP_ENV"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role=roles/cloudsql.client \
  --condition="title=$SQL_INSTANCE only,expression=$SQL_CONDITION"

gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role=roles/storage.objectUser
```

The application signs in to the bucket and the database connection as this account; no key file exists anywhere (R2.7).

The condition limits the role to the Cloud SQL instance of this environment. One project holds both environments, so without it the account of acceptance could connect to the database of production.

An environment set up before version 3.1.0 has this role without the condition: add the binding with the condition as above first, then remove the old one (and do the same for the MCP service account, section 7.1):

```bash
gcloud projects remove-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$SERVICE_ACCOUNT" \
  --role=roles/cloudsql.client \
  --condition=None
```

### 3.4 Google OAuth client (in the console)

Console, "Google Auth Platform", "Clients", "Create client":

- Application type: **Web application**; name `DimonAPP <env>`.
- Authorised redirect URI: the value of `echo "$SERVICE_URL/oauth2callback"`.

Keep the client ID and the client secret for the next step.

```bash
export GOOGLE_CLIENT_ID=<client id of this environment>
```

### 3.5 Secrets (R2.6, R2.7)

Each command reads the value from the keyboard or from a file, so no secret ends up in the shell history.

```bash
create_secret() {
  gcloud secrets create "dimonapp-$ENV-$1" \
    --replication-policy=user-managed \
    --locations="$REGION" \
    --data-file="$2"
  gcloud secrets add-iam-policy-binding "dimonapp-$ENV-$1" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role=roles/secretmanager.secretAccessor
}

# Database URL: the Unix socket of Cloud Run's Cloud SQL connection, password included
printf '%s' "postgresql+psycopg://dimonapp:$DB_PASSWORD@/dimonapp?host=/cloudsql/$PROJECT_ID:$REGION:$SQL_INSTANCE" \
  | create_secret database-url -

# Secret of the sign-in cookie: any long random text
openssl rand -hex 32 | tr -d '\n' | create_secret auth-cookie-secret -

# Client secret of the OAuth client of step 3.4: paste it, press Enter, then Ctrl-D
create_secret google-client-secret -
```

The private key registered at the RSZ, and its passphrase if it has one (`openssl pkey -in <key file> -noout -passin pass:` fails when it has):

```bash
create_secret dimona-private-key "$HOME/Projects/DimonAPP-Secrets/company_key.pem"

# Only when the key has a passphrase: paste it, press Enter, then Ctrl-D
create_secret dimona-private-key-password -
```

On macOS a secret can also come from the clipboard, which keeps it off the screen: `pbpaste | tr -d '\n' | create_secret google-client-secret -`.

A value typed at the keyboard ends with a line break; the application trims every setting it reads, so that does no harm. `unset DB_PASSWORD` when the environment runs: the password then only lives in Secret Manager.

### 3.6 Deploy (R1.7, R1.12)

Set the address of the first admin: the Google account that may sign in to the new, empty environment (R4.11).

```bash
export FIRST_ADMIN_EMAIL=<your BMC Google address>

ENV_VARS="APP_ENV=$APP_ENV"
ENV_VARS="$ENV_VARS,STORAGE_BUCKET=$BUCKET"
ENV_VARS="$ENV_VARS,AUTH_REDIRECT_URI=$SERVICE_URL/oauth2callback"
ENV_VARS="$ENV_VARS,GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID"
ENV_VARS="$ENV_VARS,FIRST_ADMIN_EMAIL=$FIRST_ADMIN_EMAIL"

SECRETS="DATABASE_URL=dimonapp-$ENV-database-url:latest"
SECRETS="$SECRETS,AUTH_COOKIE_SECRET=dimonapp-$ENV-auth-cookie-secret:latest"
SECRETS="$SECRETS,GOOGLE_CLIENT_SECRET=dimonapp-$ENV-google-client-secret:latest"
```

Add the Dimona values. They are the same in acceptance and production, and so is the private key: the RSZ test service has no sign-in of its own and takes the tokens of the live sign-in service, so one client registered at the RSZ serves both (`src/dimonapp/rsz_dimona.py`, checked against the RSZ on 10/10/2026).

```bash
ENV_VARS="$ENV_VARS,DIMONA_CLIENT_ID=<client id of the RSZ channel>"
ENV_VARS="$ENV_VARS,DIMONA_ENTERPRISE_NUMBER=<ten digits>"
ENV_VARS="$ENV_VARS,DIMONA_EMPLOYER_ID=<RSZ employer number>"
ENV_VARS="$ENV_VARS,DIMONA_JOINT_COMMISSION_ARTICLE_17=XXX"
ENV_VARS="$ENV_VARS,DIMONA_JOINT_COMMISSION_FLEXI_JOB=XXX"
SECRETS="$SECRETS,DIMONA_PRIVATE_KEY=dimonapp-$ENV-dimona-private-key:latest"

# Only when the key has a passphrase
SECRETS="$SECRETS,DIMONA_PRIVATE_KEY_PASSWORD=dimonapp-$ENV-dimona-private-key-password:latest"
```

Then deploy:

```bash
gcloud run deploy "$SERVICE" \
  --image="$IMAGE" \
  --region="$REGION" \
  --service-account="$SERVICE_ACCOUNT" \
  --add-cloudsql-instances="$PROJECT_ID:$REGION:$SQL_INSTANCE" \
  --set-env-vars="$ENV_VARS" \
  --set-secrets="$SECRETS" \
  --port=8080 \
  --memory=1Gi \
  --min-instances=0 \
  --max-instances=1 \
  --timeout=3600 \
  --session-affinity \
  --allow-unauthenticated
```

- `--max-instances=1`: one instance, so the migrations at start-up never run twice at once and every browser session stays on the same instance (R1.12).
- `--allow-unauthenticated`: the address is public over HTTPS; the application itself asks everybody to sign in (R1.8). If the organisation forbids public services, the command says so: an organisation admin must then allow `allUsers` for this project.
- `--timeout=3600`: a browser session is one long connection; the Dimona call itself gives up after 2 minutes.
- `--min-instances=0`: the service stops when nobody uses it and takes some seconds to start again. Use `1` for production if that wait is a nuisance (it costs more).
- At start-up the container writes the Streamlit secrets file, applies the database migrations and adds the first admin.

Open `$SERVICE_URL`.

## 4. Checks after a deployment

### Acceptance: smoke test

1. The page opens over HTTPS; the sidebar says **ACC**; the footer shows the version of the image. Once a worker opens the application (the real declaration below), the log names the RSZ test service (`Dimona client: RSZ service at https://services-sim.socialsecurity.be/REST/dimona/v2.`).
2. "Se connecter avec Google" with the first admin's account opens the admin console.
3. Configuration: fill in BMC's details and the limits of the year; save both.
4. Travailleurs: create a local worker of type article 17 with the eleven rates, a postal address and a national register number the RSZ test service knows.
5. Autorisations: upload a contract and a qualification for that worker; download one again. `gcloud storage ls -r "gs://$BUCKET"` shows the two files.
6. As admin: the dashboard shows the cost; Rapport mensuel exports the payment file; Fiches fiscales downloads the zip.
7. `gcloud sql backups list --instance="$SQL_INSTANCE"` shows a backup the day after.

### Acceptance: a real declaration at the RSZ test service

1. Sign out; sign in as the worker of the smoke test.
2. Declare an activity: the answer comes from the RSZ (accepted with a declaration number, or refused with the reason). Cancel it again.
3. Check both in the Dimona portal of the RSZ simulation environment.

### Production

Only after acceptance passed. The sidebar says **PROD**, and once a worker opens the application the log names the live RSZ service (`https://services.socialsecurity.be/REST/dimona/v2`); every declaration is a real Dimona. Enter the real limits, BMC's details, workers and documents; do not copy data from another environment. Then set up the MCP service (section 7) and check it (section 7.5).

## 5. Update an environment to a new release

The section "Releasing a new version" of `README.md` has the same steps ready to copy, with the checks. In short: build the image of the new version (section 2), then, with the variables of section 3 set for the environment:

```bash
gcloud run services update "$SERVICE" --region="$REGION" --image="$IMAGE"
```

Always locally first (`make test`, `make run`), then acceptance, then production, with the same image for the two. The migrations run when the new container starts. Settings and secrets stay as they are; change one with `--update-env-vars` or `--update-secrets`.

To go back to the previous version, deploy its image again the same way. A migration is not undone by that: check the release notes of the pull requests in between first.

## 6. Day-to-day

- **Logs:** `gcloud run services logs read "$SERVICE" --region="$REGION" --limit=100`. The logs never hold national register numbers, IBANs or passwords (R3.5).
- **More admins:** there is no screen for admins. Add one in the console: Cloud SQL, the instance, "Cloud SQL Studio", database `dimonapp`, user `dimonapp` with the password of the secret `dimonapp-<env>-database-url`, then `INSERT INTO admins (email) VALUES ('name@example.com');` (lower case). `FIRST_ADMIN_EMAIL` only works while the table is empty.
- **Restore a backup:** `gcloud sql backups list --instance="$SQL_INSTANCE"`, then `gcloud sql backups restore <backup id> --restore-instance="$SQL_INSTANCE"`. This replaces the whole database.
- **Rotate a secret:** `gcloud secrets versions add "dimonapp-$ENV-<name>" --data-file=-`, then deploy the service again so it reads the new version.
- **Yearly:** enter the indexed limits of the new year in Configuration; when FOD Financiën publishes the Belcotax schema of the new income year (around December), store it unmodified as `src/dimonapp/schemas/belcotax-<year>.xsd` and set `BELCOTAX_SCHEMA_YEAR` in `src/dimonapp/belcotax.py` to that year, before the fiches of that year are submitted (FDS 7.6, R14.4).

## 7. MCP server

The MCP server (FDS section 15) runs as a Cloud Run service of its own, `dimonapp-mcp-<env>`, from the same image as the application with another start command (R20.8). It serves two endpoints: `/public/mcp`, without sign-in or database (R20.5), and `/mcp`, the data tools, behind Google sign-in for active admins only (R20.6). In acceptance and production the service refuses to start without sign-in and its database user, so the data tools are never online without sign-in (R20.7). Acceptance and production each have one (FDS 15.3).

The application's migrations create what the MCP server reads (FDS section 15.4, from version 3.1.0a3): the schema `mcp` with its views and the function `mcp.is_active_admin`, and the role `dimonapp_mcp`, which cannot sign in and may only read those views. The database user `dimonapp` of section 3.1 creates the role; Cloud SQL gives that user the right to create roles. Deploy the application with the new image first, so the migrations have run.

With the variables of section 3 set for the environment and `IMAGE` of section 2:

```bash
export MCP_SERVICE="dimonapp-mcp-$ENV"
export MCP_SERVICE_ACCOUNT="dimonapp-mcp-$ENV@$PROJECT_ID.iam.gserviceaccount.com"
export MCP_SERVICE_URL="https://$MCP_SERVICE-$PROJECT_NUMBER.$REGION.run.app"
export MCP_DB_USER="dimonapp-mcp-$ENV@$PROJECT_ID.iam"
export MCP_OAUTH_BUCKET="dimonapp-mcp-$ENV-oauth"
echo "$MCP_SERVICE_URL"
```

### 7.1 Service account (R20.9)

```bash
gcloud iam service-accounts create "dimonapp-mcp-$ENV" --display-name="DimonAPP MCP $APP_ENV"

for role in roles/cloudsql.client roles/cloudsql.instanceUser; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$MCP_SERVICE_ACCOUNT" \
    --role="$role" \
    --condition="title=$SQL_INSTANCE only,expression=$SQL_CONDITION"
done
```

- `cloudsql.client` lets the service use Cloud Run's built-in Cloud SQL connection; `cloudsql.instanceUser` lets it sign in as its IAM database user (section 7.2). Neither gives any right inside a database: those come from the role `dimonapp_mcp` only.
- The condition limits the role to the Cloud SQL instance of this environment, as for the application (section 3.3). One project holds both environments, so without it the account of acceptance could connect to the database of production.
- The account gets no other role. It reads only its own secrets and uses only its own bucket (section 7.3): never the document bucket, the Dimona key or a secret of the application. Never add it to `create_secret` of section 3.5, which grants the application's account.

An environment set up before version 3.1.0 has the two roles without the condition: add them with the condition as above first, then remove the old bindings. The last command shows the project roles of the two accounts of the environment, each with the title of its condition:

```bash
for role in roles/cloudsql.client roles/cloudsql.instanceUser; do
  gcloud projects remove-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$MCP_SERVICE_ACCOUNT" \
    --role="$role" \
    --condition=None
done

gcloud projects get-iam-policy "$PROJECT_ID" \
  --flatten='bindings[].members' \
  --filter="bindings.members:$SERVICE_ACCOUNT OR bindings.members:$MCP_SERVICE_ACCOUNT" \
  --format='table(bindings.role,bindings.members,bindings.condition.title)'
```

### 7.2 Database user (R20.10, FDS 15.4)

The service signs in to Cloud SQL as the IAM database user of its service account: a fresh access token of that account is the password of every new connection, so there is no database password at all.

```bash
# Allow IAM sign-in on the instance (no restart needed). This sets the instance's whole list
# of flags: name any flag the instance already has as well.
gcloud sql instances patch "$SQL_INSTANCE" --database-flags=cloudsql.iam_authentication=on

gcloud sql users create "$MCP_DB_USER" --instance="$SQL_INSTANCE" --type=cloud_iam_service_account
```

Then make that user a member of the read-only role. In the console, open Cloud SQL, the instance, then Cloud SQL Studio; sign in to the database `dimonapp` as the user `dimonapp` (its password is in the secret `dimonapp-$ENV-database-url`, between `dimonapp:` and `@`) and run, with the user's name filled in:

```sql
GRANT dimonapp_mcp TO "dimonapp-mcp-<env>@<project-id>.iam";
```

The IAM user has no other right in the database: the views of `mcp` and the function `mcp.is_active_admin` are all it can use (R20.10).

### 7.3 Sign-in (R20.6, R20.9)

**OAuth client.** In the console, APIs & Services, Credentials: Create credentials, OAuth client ID, Web application, named `DimonAPP MCP <env>`. No JavaScript origin. One authorised redirect URI, `$MCP_SERVICE_URL/auth/callback`. It uses the existing Internal consent screen of section 3.4. Keep the client ID; the client secret goes straight into a secret below.

```bash
export MCP_GOOGLE_CLIENT_ID=<client id of the MCP OAuth client>
```

**Secrets.** Like those of section 3.5, but named after the MCP service and readable by its account only:

```bash
create_mcp_secret() {
  gcloud secrets create "$MCP_SERVICE-$1" \
    --replication-policy=user-managed \
    --locations="$REGION" \
    --data-file="$2"
  gcloud secrets add-iam-policy-binding "$MCP_SERVICE-$1" \
    --member="serviceAccount:$MCP_SERVICE_ACCOUNT" \
    --role=roles/secretmanager.secretAccessor
}

# Client secret of the MCP OAuth client: copy it, then
pbpaste | tr -d '\n' | create_mcp_secret google-client-secret -

# The key that signs the tokens of the OAuth proxy and encrypts its stored state
openssl rand -hex 32 | tr -d '\n' | create_mcp_secret jwt-signing-key -
```

**State of the OAuth proxy.** The proxy stores the MCP clients it registered and the Google tokens it holds for them, encrypted. A bucket of its own keeps them across restarts and scales to zero:

```bash
gcloud storage buckets create "gs://$MCP_OAUTH_BUCKET" \
  --location="$REGION" \
  --uniform-bucket-level-access \
  --public-access-prevention

gcloud storage buckets add-iam-policy-binding "gs://$MCP_OAUTH_BUCKET" \
  --member="serviceAccount:$MCP_SERVICE_ACCOUNT" \
  --role=roles/storage.objectUser
```

A new signing key makes what is stored unreadable: MCP clients then simply register and sign in again. The bucket holds nothing in plain text, but never give anyone else access to it.

**Clean-up after 30 days (FDS 15.3).** Anyone can register an MCP client with the proxy without signing in, and the proxy never deletes what it stores, so a lifecycle rule deletes every file of the store 30 days after it was last written. It only matches the `.json` files of the store and the `.tmp` files a write may leave: the folder objects of the mount (names ending in `/`) stay, as the mounted folders would otherwise disappear. A token in use is written again whenever it is refreshed; a client registration is not, so an MCP client that registered with the proxy signs in again once its registration is 30 days old. Claude does not register (it names itself by the address of a client description, CIMD), so it is not affected.

```bash
LIFECYCLE_FILE=$(mktemp)
cat > "$LIFECYCLE_FILE" <<'EOF'
{"lifecycle": {"rule": [{"action": {"type": "Delete"}, "condition": {"age": 30, "matchesSuffix": [".json", ".tmp"]}}]}}
EOF
gcloud storage buckets update "gs://$MCP_OAUTH_BUCKET" --lifecycle-file="$LIFECYCLE_FILE"
gcloud storage buckets describe "gs://$MCP_OAUTH_BUCKET" --format='yaml(lifecycle_config)'
```

The last command shows the rule: a `Delete` action with `age: 30` and the two suffixes.

### 7.4 Deploy (R20.8)

```bash
MCP_DATABASE_URL="postgresql+psycopg://${MCP_DB_USER/@/%40}@/dimonapp?host=/cloudsql/$PROJECT_ID:$REGION:$SQL_INSTANCE"

MCP_ENV_VARS="APP_ENV=$APP_ENV"
MCP_ENV_VARS="$MCP_ENV_VARS,MCP_DATABASE_URL=$MCP_DATABASE_URL"
MCP_ENV_VARS="$MCP_ENV_VARS,MCP_DATABASE_IAM_LOGIN=true"
MCP_ENV_VARS="$MCP_ENV_VARS,MCP_BASE_URL=$MCP_SERVICE_URL"
MCP_ENV_VARS="$MCP_ENV_VARS,MCP_GOOGLE_CLIENT_ID=$MCP_GOOGLE_CLIENT_ID"
MCP_ENV_VARS="$MCP_ENV_VARS,MCP_OAUTH_FOLDER=/oauth"

MCP_SECRETS="MCP_GOOGLE_CLIENT_SECRET=$MCP_SERVICE-google-client-secret:latest"
MCP_SECRETS="$MCP_SECRETS,MCP_JWT_SIGNING_KEY=$MCP_SERVICE-jwt-signing-key:latest"

gcloud run deploy "$MCP_SERVICE" \
  --image="$IMAGE" \
  --region="$REGION" \
  --service-account="$MCP_SERVICE_ACCOUNT" \
  --command=python \
  --args=-m,dimonapp.mcp_service \
  --add-cloudsql-instances="$PROJECT_ID:$REGION:$SQL_INSTANCE" \
  --set-env-vars="$MCP_ENV_VARS" \
  --set-secrets="$MCP_SECRETS" \
  --add-volume="name=oauth,type=cloud-storage,bucket=$MCP_OAUTH_BUCKET,mount-options=uid=1000;gid=1000" \
  --add-volume-mount=volume=oauth,mount-path=/oauth \
  --port=8080 \
  --memory=512Mi \
  --min-instances=0 \
  --max-instances=1 \
  --allow-unauthenticated
```

- `--command` and `--args`: the start command of the MCP service instead of the application's. It never applies migrations; the application's service does that (R1.10).
- `MCP_DATABASE_URL` names the IAM user without a password (the `@` in its name written as `%40`) and is not a secret; `MCP_DATABASE_IAM_LOGIN=true` makes the service sign in with its token.
- `--add-volume` and `--add-volume-mount`: the bucket of section 7.3 appears as the folder `/oauth`, owned by the unprivileged user of the image (id 1000), which may then write in it.
- `--max-instances=1` and `--min-instances=0`: one instance at most (R1.12); it stops when nobody uses it.
- `--allow-unauthenticated`: Cloud Run lets every request through. `/public/mcp` needs no sign-in (R1.8, R20.5); `/mcp` checks the Google sign-in itself (R20.6).

### 7.5 Check

```bash
uv run fastmcp list "$MCP_SERVICE_URL/public/mcp"
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$MCP_SERVICE_URL/mcp"
curl -s "$MCP_SERVICE_URL/.well-known/oauth-protected-resource/mcp"
gcloud run services logs read "$MCP_SERVICE" --region="$REGION" --limit=20
```

The first command lists one tool, `about`; the second prints `401`, as `/mcp` needs sign-in; the third shows the sign-in that MCP clients discover. The log shows `/mcp is served with Google sign-in, for active admins only.`

Then connect from Claude: Settings, Connectors, Add custom connector, with the address `$MCP_SERVICE_URL/mcp`, and sign in with the Google account of an active admin. Ask, for example, whether last month looks correct. A Google account that is not an active admin gets no access. Only Claude and MCP clients on the admin's own machine (`http://localhost`, `http://127.0.0.1`) can sign in: the proxy refuses any other redirect address (FDS 15.3, R20.23).

A new release updates this service with the same image as the application (README, "Releasing a new version").

## Settings of the service

| Variable | From | Environments |
|---|---|---|
| `APP_ENV` | plain value | acc, prod |
| `STORAGE_BUCKET` | plain value | acc, prod |
| `AUTH_REDIRECT_URI` | plain value | acc, prod |
| `GOOGLE_CLIENT_ID` | plain value | acc, prod |
| `FIRST_ADMIN_EMAIL` | plain value | acc, prod |
| `DATABASE_URL` | Secret Manager | acc, prod |
| `AUTH_COOKIE_SECRET` | Secret Manager | acc, prod |
| `GOOGLE_CLIENT_SECRET` | Secret Manager | acc, prod |
| `DIMONA_CLIENT_ID`, `DIMONA_ENTERPRISE_NUMBER`, `DIMONA_EMPLOYER_ID`, `DIMONA_JOINT_COMMISSION_*` | plain values | acc, prod |
| `DIMONA_PRIVATE_KEY`, `DIMONA_PRIVATE_KEY_PASSWORD` | Secret Manager | acc, prod |
| `PORT` | set by Cloud Run | acc, prod |

`STORAGE_FOLDER`, `FAKE_DIMONA_OUTCOME`, `SEED_*` and `DIMONA_PRIVATE_KEY_PATH` are for local work only and are not set in GCP.

The MCP service (section 7) reads only its own settings, never one of the application's:

| Variable | From | Environments |
|---|---|---|
| `APP_ENV` | plain value | acc, prod |
| `MCP_DATABASE_URL` | plain value (no password in it) | acc, prod |
| `MCP_DATABASE_IAM_LOGIN` | plain value, `true` | acc, prod |
| `MCP_BASE_URL` | plain value, the address of the service | acc, prod |
| `MCP_GOOGLE_CLIENT_ID` | plain value | acc, prod |
| `MCP_OAUTH_FOLDER` | plain value, `/oauth` | acc, prod |
| `MCP_GOOGLE_CLIENT_SECRET` | Secret Manager | acc, prod |
| `MCP_JWT_SIGNING_KEY` | Secret Manager | acc, prod |
| `PORT` | set by Cloud Run | acc, prod |

`MCP_HOST` is for local work only (`make mcp`).
