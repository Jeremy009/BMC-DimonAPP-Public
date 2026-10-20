# DimonAPP V3.0: Functional Design Specification

> Source of truth for the build. If this file and the code disagree, the FDS wins: change the FDS first, then the code.

Brussels Monkeys Climbing ASBL

**DimonAPP V3.0**

Timesheets, Dimona declarations and fiscal fiche 281.27

| **Document** | **Value**                                                            |
|--------------|----------------------------------------------------------------------|
| Type         | Functional Design Specification (FDS)                                |
| Version      | 4.10 (Android home screen icon) |
| Date         | 17 October 2026                                                      |
| Owner        | BMC board                                                            |
| Status       | Built; acceptance deployed, production to follow                     |

**Version history**

| **Version** | **Date** | **Changes** |
|---|---|---|
| 1.0 to 3.9 | Before 10 October 2026 | Drafts: scope, roles, worker types, activity types, Dimona flow, data model, French interface, common page layout, requirements list and mockups. |
| 4.0 | 10 October 2026 | Technical choices, Belcotax schema and passwords; ready for build. |
| 4.2 | 13 October 2026 | In line with the application as built and deployed. Requirements added: R4.11, R4.12, R6.9 to R6.12, R7.14 to R7.16, R11.8 to R11.10, R12.10 and R18.9. Requirements changed: R2.1 to R2.4, R2.6, R3.1, R3.6, R5.3, R6.1, R6.3, R6.5, R6.6, R6.8, R7.3, R7.5, R7.6, R7.10, R8.3, R8.5, R10.3, R10.6, R10.7, R11.2, R12.1, R12.3, R15.4, R16.4, R17.3, R18.4, R18.6 and R18.8. Screen mockups replaced by screenshots of the application. |
| 4.3 | 14 October 2026 | Sign-in duration: a sign-in ends after 12 hours, or after 30 minutes without any action, and a local account is told its session has expired. Requirement added: R4.13. |
| 4.5 | 14 October 2026 | Security hardening after an audit: five wrong passwords lock a username of the local form for 15 minutes, a password has at least 10 characters, the 30 idle minutes count per account instead of per browser tab, and the browser never shows the technical details of an error. Requirements added: R3.8, R4.14. Requirements changed: R4.13, R11.9. Tables added: sign_in_failures, last_actions. Open item 6 closed. |
| 4.4 | 14 October 2026 | Several article 17 activities on one day: the RSZ refuses a second Dimona IN for the same day, so later activities update the hours of the period of that day, and a cancellation lowers them while other activities remain. Requirements added: R8.9, R8.10, R9.6 and R9.7. Requirement changed: R9.3. Open item 8 added for flexi-jobs. |
| 4.6 | 15 October 2026 | A contract or qualification that an activity relied on is evidence of the work and is kept: it can no longer be deleted, and only its end date can still be changed. Requirements changed: R12.6, R12.7. |
| 4.7 | 17 October 2026 | The dashboard shows a calendar of the accepted activities of the month and hides the alerts heading when there is no alert; the monthly report moves between months with arrows; a new Activities tab lists the activities of every worker for a month; the admin tabs are reordered. Requirements added: R10.8, R19.1. Requirements changed: R13.1 (month arrows instead of the dropdown, section 7.5), R18.1 (the English menus of the Activities table are accepted). |
| 4.8 | 17 October 2026 | Release candidates: the application is complete, so the version moves from the betas (3.0.0bN) to release candidates (3.0.0rc1, 3.0.0rc2 and so on), still raised with every pull request until the first release 3.0.0. Requirement changed: R18.8. |
| 4.9 | 17 October 2026 | Appendix B, the screenshots of every screen, is removed: the application itself now shows the screens, and the text of this document describes them. |
| 4.10 | 17 October 2026 | Android home screen icon: the application serves a web app manifest, so a phone with Android shows the DimonAPP icon and name on its home screen and opens the application without the browser bar, as an iPhone does. Requirement added: R18.10. |

## 1. Purpose and scope

DimonAPP V3.0 is the simple internal web application Brussels Monkeys Climbing (BMC) needs to administer the people who work for the association. The application covers four needs:

1.  Timesheet management: workers declare the activities they will perform; the admin sees monthly totals and pays workers.

2.  Dimona declarations to the RSZ for article 17 workers and flexi-jobbers, at the moment an activity is declared.

3.  Year-end generation of the fiscal fiche 281.27 (verenigingswerk / article 17), both as PDF and as Belcotax-on-web XML.

4.  Authorisation management: a worker may only perform an activity when a valid contract and a valid qualification covering it are on file.

BMC already operates an in-house Python + Streamlit tool (DimonAPP V2, also called Dimona B2) with a working, certificate-based connection to the RSZ Dimona API. The new application reuses that proven integration rather than rebuilding it.

**Guiding principle:** the application must stay simple. Code must be easy to read and easy to test. When two designs are possible, the most pragmatic and readable one wins.

## 2. Roles and accounts

The application has two profiles, implemented as two fully separate account types.

|             | **Worker account**                                                                            | **Admin account**                                                             |
|-------------|-----------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------|
| Purpose     | Declares and cancels own activities, views own timesheet and own authorisations               | Administers workers, authorisations, compensation, limits, reports and fiches |
| Regime data | Yes (type, national number, IBAN, rates)                                                      | None                                                                          |
| Login       | Google sign-in (BMC Workspace address) or local username and password provisioned by an admin | Google sign-in only                                                           |
| Stored in   | workers table                                                                                 | admins table                                                                  |

- An admin is never stored as a worker and has no worker-side access.

- A person with both roles (for example the president) has two separate accounts and logs in with the one matching the task at hand.

- There is no self-registration. Admins create every worker account and hand over local credentials. Passwords are only ever stored as a hash.

- A deactivated account is told so at sign-in, with the message "Ce compte est désactivé. Contactez un administrateur BMC.": on the local form only when the password is right, after Google sign-in always (Google has proven who it is). Every other refusal of the local form keeps one general message, so the form reveals nothing about which accounts exist.

- Five wrong passwords in a row for one username of the local form, each within 15 minutes of the one before, lock that username for 15 minutes: every attempt is then refused, even with the right password, with the message "Trop de tentatives de connexion. Réessayez dans 15 minutes." An unknown username is locked in exactly the same way, so the lock reveals nothing about which accounts exist. A successful sign-in clears the count, and so does a new password set by an admin, which is how an admin unlocks a worker at once. The typed username is only stored as a hash, because people sometimes type their password in that field.

- A sign-in lasts at most 12 hours, and ends sooner after 30 minutes without any action, so a session left open on a shared computer does not stay usable. Both caps apply to Google and local sign-in. The page only runs when the person acts, so an expired sign-in shows the login page at the next click; that click does nothing else, so a declaration sent with it is not made. A local account then reads "Votre session a expiré. Veuillez vous reconnecter." above the form. A Google account sees the login page without it: Streamlit's Google sign-out reloads the page, which leaves nothing to tell it from an ordinary visit. The 30 minutes count per account, in the database: an action in any tab or on any device counts, and a refresh or a new tab does not start them again. A sign-in that has just been made counts as an action.

- The first admin of an environment: there is no screen to manage admins, so a new environment would have nobody who can sign in. The Google address given in the setting FIRST_ADMIN_EMAIL becomes the admin at start-up when the admins table is still empty; once an admin exists the setting does nothing. Further admins are added directly in the database (`docs/DEPLOYMENT.md`).

**Rationale:** two account types keep each view single-purpose, avoid "which hat is this person wearing" logic throughout the code, and make the rule "admins are Google-only" trivial to enforce.

## 3. Technology and platform

### 3.1 Stack

- **Language:** Python

- **UI:** Streamlit, tab-based, one view per account type

- **Python project:** managed with uv; dependencies and project metadata live in pyproject.toml, and the uv.lock lock file is committed (see section 3.5)

- **Developer commands:** a Makefile with at least make test and make run (see section 3.5)

- **Packaging:** Docker, one image for all environments

- **Cloud:** Google Cloud Platform (BMC already runs on Google Workspace), in one GCP project, dimonapp, that holds acceptance and production

- **Compute:** Cloud Run, publicly reachable over HTTPS, hence authentication is mandatory

- **Database:** Cloud SQL for PostgreSQL (see section 4)

- **File storage:** Google Cloud Storage bucket for uploaded contract and qualification documents (see section 4)

### 3.2 Environments

Three environments, kept as identical as possible. They differ in one deliberate way, the Dimona service:

| **Environment** | **Label** | **Runs** | **Dimona** |
|---|---|---|---|
| Test | TEST | Locally, on the developer's machine | No Dimona call at all: a fake service inside the application answers every declaration and cancellation |
| Acceptance | ACC | In GCP | Real calls to the RSZ Dimona test (simulation) service |
| Production | PROD | In GCP | Real calls to the live RSZ Dimona service |

- Acceptance and production are each a Cloud Run service paired with its own Cloud SQL database and its own document bucket, in the same region, with the same schema and configuration shape.

- The test environment is not deployed to GCP. It is the application run locally (make run) against a throwaway PostgreSQL in Docker, with fake data only (section 4).

- The same Docker image is deployed to acceptance and to production. A release goes to acceptance first, so every database migration runs there before it reaches production.

- No data is copied between environments: production holds the real data, acceptance only fictitious workers that the RSZ test service knows.

- The environment is named by one injected value (TEST, ACC or PROD). The code uses that name for two things only: the label in the sidebar and the Dimona service of the table above. The RSZ address is therefore not a separate setting, so an environment can never call the wrong service; the start-up log names the service in use. Everything else that differs is injected configuration: database connection, storage bucket and the Dimona identifiers and key.

### 3.3 Configuration and secrets

- All configuration and secrets are read from environment variables.

- Locally, a developer uses a git-ignored .env file.

- In GCP, the same variables are set on the Cloud Run service at deploy time, for acceptance and for production. Every secret (the database connection with its password, the secrets of the Google sign-in, the Dimona key and its passphrase) comes from GCP Secret Manager; values that are not secret (environment name, bucket name, redirect address, Google client ID, the RSZ identifiers, the first admin's address) are plain values of the service. `docs/DEPLOYMENT.md` lists them and holds the exact commands.

- Values are trimmed when read, so a secret stored with a line break at its end still works.

- The environment name and the database connection are required: without them the application stops at start-up instead of guessing. Acceptance and production also refuse to start without the RSZ identifiers and the Dimona key.

- In GCP each environment has its own service account, its own secrets and its own Google OAuth client. The Cloud Run service runs as that service account, which can read only the secrets and the document bucket of its own environment.

- The Dimona certificate, API key and database password are never baked into the Docker image nor committed to the repository. This is a crucial requirement.

### 3.4 Language, common page layout, help and versioning

The look and feel follows the current DimonAPP V2 so users recognise it. Every page, for workers and admins and including the login page, shares the same frame:

- **Language:** the whole user interface is in French: every label, button, message, error, table header, month name and date. Numbers and amounts use French formatting (for example 1 234,50 €, 2,5 h; dates DD/MM/YYYY). Calendars (date pickers) are French in every browser, whatever its language: French month and day names, weeks starting on Monday. This document uses English names; the French labels are listed in the table below. One deliberate exception: the table of the Activities tab (section 7.8) is interactive, so the admin can sort, search, enlarge and export it; the menus of that table (sort, format, search, download, full screen) are Streamlit's own and only exist in English. Its headers and content stay French. Every other read-only table is a plain table without those menus.

- **Theme:** the default Streamlit light theme, as in DimonAPP V2.

- **Logos:** DimonAPP uses two logos, both stored with the code:

  - favicon (favicon.png, orange rounded square): the small icon shown next to the address bar and in browser tabs, and the icon used when a user adds DimonAPP to the home screen of an iPhone or iPad ("Add to Home Screen") or of an Android phone ("Ajouter à l'écran d'accueil").

  - logoarriere (logoarriere.png, orange oval): the logo shown inside the application itself, at the top of the sidebar on every page.

<table>
<colgroup>
<col style="width: 50%" />
<col style="width: 50%" />
</colgroup>
<tbody>
<tr class="odd">
<td><p><img src="../src/dimonapp/assets/favicon.png" title="favicon" width="110" alt="favicon logo" /></p>
<p><em>favicon</em></p></td>
<td><p><img src="../src/dimonapp/assets/logoarriere.png" title="logoarriere" width="75" alt="logoarriere logo" /></p>
<p><em>logoarriere</em></p></td>
</tr>
</tbody>
</table>

Technical note: Streamlit sets the favicon through page_icon, but it does not add the apple-touch-icon link that iOS uses for home screen icons. The application must therefore serve a 180 x 180 px PNG version of the favicon and add \<link rel="apple-touch-icon" href="..."\> to the served page (for example by patching Streamlit's index.html when the Docker image is built). Without it, iOS falls back to a screenshot of the page.

Android does not read the apple-touch-icon: it takes the home screen icon, the name and the way the application opens from a web app manifest, which Streamlit does not provide either. The application therefore also serves a manifest, linked from the served page with \<link rel="manifest" href="..."\> in the same way. The manifest names the application "DimonAPP", opens it on its start page without the browser bar (display standalone, as an iPhone does from its home screen) and gives the favicon at 192 x 192 and 512 x 512 px. Android cuts every home screen icon to the shape of the phone (a circle, a rounded square and so on), so these two icons are a full orange square with the climber of the favicon inside the central circle of 80 % of the width, which no shape cuts (a "maskable" icon). Without the manifest, Android makes a plainer shortcut from the small browser tab icon, which opens in the browser.

- **Sidebar:** the logoarriere logo at the top, followed by these blocks in this order (no "About" heading):

  - "DimonAPP" with an environment label: "TEST" in the test environment, "ACC" in acceptance, "PROD" in production.

  - A one-line explanation of the application.

  - Once signed in: "Connecté en tant que :" and, on the next line in bold, "\<name\> - \<type\>", where the type is Volontaire, Article 17, Flexijob, Indépendant, or Admin for admin accounts (for example "Lotte Peeters - Article 17").

  - A heading "Comment utiliser la DimonAPP ?" with the button "Consulter les SOPs".

  - Once signed in: a heading "Se déconnecter" with the button "Se déconnecter".

  The blocks follow each other directly, without lines or extra space between them.

- **SOP link:** the "Consulter les SOPs" button opens https://www.brusselsmonkeysclimbing.com/sop in a new browser tab. It is shown in the worker view, the admin console and on the login page. The link is fixed (part of the application configuration), not editable from the UI.

- **Main area:** the title "DimonAPP" with a one-line subtitle, then the tabs. Each tab starts with a heading repeating the tab name.

- **Footer:** a full-width footer at the bottom of every page reading "V\<x.y.z\> - © \<current year\> Brussels Monkeys Climbing", with a link to www.brusselsmonkeysclimbing.com below it.

- **Dimona service:** the footer does not name the Dimona service. The service follows from the environment alone (section 3.2), the sidebar shows the environment, and the start-up log names the service in use.

- **Versioning:** the application uses semantic versioning (MAJOR.MINOR.PATCH), with 3.0.0 as the first release. Until then the version is a pre-release of it, raised with every pull request, so the footer tells exactly which build is running: betas during the build (3.0.0b6, 3.0.0b7 and so on), then release candidates once the application is complete (3.0.0rc1, 3.0.0rc2 and so on). The version is defined in one place in the code and built into the Docker image, so the footer always shows the version that is actually deployed; the same image shows the same version in every environment.

French interface labels for the terms used in this document:

| **English (this document)**                                                                                  | **French (interface)**                                                                                      |
|--------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------|
| Worker types: Vrijwilliger, Article 17, Flexi-jobber, Freelancer, Admin                                      | Volontaire, Article 17, Flexijob, Indépendant, Admin                                                        |
| Worker tabs: Create activity, Cancel activity, Monthly overview, My authorisations                           | Déclarer une activité, Annuler une activité, Aperçu mensuel, Mes documents                                  |
| Admin tabs: Dashboard, Monthly report, Activities, Workers, Authorisations, Compensation, Year-end fiches, Configuration | Tableau de bord, Rapport mensuel, Activités, Travailleurs, Autorisations, Rémunération, Fiches fiscales, Configuration |
| Opening the gym (permanence), BMC courses, Group courses without and with instructor | Permanence, Cours BMC, Cours groupe sans mono, Cours groupe avec mono |
| Group travel, Rope supplement (the two supplements) | Déplacement groupe, Supplément corde 9 à 14 |
| Route setting easy, medium, hard | Ouverture 4A - 5C, Ouverture 6A - 6C, Ouverture 7A et plus |
| Route cleaning easy, hard (taking routes down) | Démontage facile, Démontage difficile (cordes 9 à 14) |
| Contract, Qualification                                                                                      | Contrat, Qualification                                                                                      |
| Hourly, Fixed price                                                                                          | Horaire, Prix fixe                                                                                          |
| Dimona status: ok, pending, rejected, not applicable; cancelled                                              | OK, En attente, Refusée, Non applicable; Annulée                                                            |
| Quarters Q1 to Q4, YEAR                                                                                      | T1 à T4, ANNÉE                                                                                              |

### 3.5 Python project, structure and developer commands

- **uv and pyproject.toml:** the project is a standard Python project managed with uv. pyproject.toml holds the project metadata, the Python version, the runtime dependencies and a separate group for development dependencies (such as pytest). The uv.lock file is committed so every developer and the Docker build install exactly the same versions; the Docker image installs the locked runtime dependencies only (uv sync --frozen --no-dev).

- **Folder structure:** the application code lives in a src folder and the automated tests in a separate tests folder:

> dimonapp/
>
> pyproject.toml project metadata and dependencies
>
> uv.lock locked dependency versions (committed)
>
> Makefile developer commands
>
> Dockerfile single image for every environment
>
> .env.example template for the git-ignored local .env
>
> src/dimonapp/ application code
>
> app.py Streamlit entry point
>
> assets/ favicon.png, logoarriere.png
>
> tests/ automated tests (pytest)

- **Makefile:** common commands are wrapped in a Makefile so nobody has to remember the exact uv or Streamlit command line. It implements at least:

  - make test: runs the full test suite (uv run pytest).

  - make run: starts the application locally (uv run streamlit run src/dimonapp/app.py), reading configuration from the local .env file. It first writes .streamlit/secrets.toml from the same .env file, so Google sign-in also works locally (section 3.6).

The Makefile also has: make lint (Ruff formats and checks the code), make db (starts the local PostgreSQL), make migrate (applies the migrations), make seed (fills an empty local database with fake data; refused in production and on a database that already holds workers), make docker-build (builds the image) and make test-rsz (declares and cancels one activity at the RSZ test service; never part of make test).

### 3.6 Technical choices

These choices keep the implementation consistent and simple:

| **Topic**                   | **Choice**                                                                                                                    | **Why**                                                                                                                                                                                                                                      |
|-----------------------------|-------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Database access             | SQLAlchemy 2.0 (typed ORM) with the psycopg 3 driver                                                                          | The most widely used and best documented Python database toolkit; works natively with PostgreSQL features used here (arrays, enums); plays well with Alembic and pytest.                                                                     |
| Schema changes (migrations) | Alembic, with one versioned migration script per schema change, committed in the repository                                   | The standard migration tool for SQLAlchemy. Migrations run automatically (alembic upgrade head) when the container starts, before Streamlit, and are also available as make migrate locally.                                                 |
| Google sign-in              | Streamlit's built-in OIDC login: st.login(), st.user and st.logout() with Google as provider (Streamlit's auth extra, which installs Authlib and httpx)               | Native to Streamlit, no custom OAuth code. After sign-in, the e-mail in st.user is matched against the admins table and then the workers table (auth_method = google); an unknown or inactive e-mail is refused with a French error message. |
| Local accounts              | A username and password form in the app; passwords hashed with Argon2 (argon2-cffi)                                           | Argon2 is the current recommended password hash. The signed-in local user is kept in st.session_state (a browser refresh asks to sign in again, which is acceptable).                                                                        |
| Streamlit secrets           | At start-up, a small script writes .streamlit/secrets.toml (the \[auth\] section) from environment variables                  | st.login reads its settings from secrets.toml, while the project rule is environment variables everywhere (section 3.3). The generated file is never committed or baked into the image.                                                      |
| Cloud SQL connection        | Cloud Run's built-in Cloud SQL connection (Unix socket); TCP to a local PostgreSQL container in development                   | No extra connector library in the code; only the connection URL differs per environment.                                                                                                                                                     |
| Cloud Run scaling           | Maximum one instance                                                                                                          | Ample for BMC, avoids concurrent migrations at start-up, and keeps Streamlit's websocket sessions on one instance.                                                                                                                           |
| Tests                       | pytest; database tests run against a throwaway PostgreSQL started by testcontainers; the Dimona API is always mocked in tests | make test works on any machine with Docker, without manual setup, and tests never call RSZ.                                                                                                                                                  |
| Document storage | The google-cloud-storage library behind a small storage interface, with a local folder as the second implementation | The same code stores a document in the bucket in GCP and in a folder locally and in tests. |
| Payment file and Belcotax file | XML written with lxml and checked against the official schema stored with the code | A wrong file is caught before it leaves the application. |
| Fiche 281.27 PDF | fpdf2, with the DejaVu Sans font stored with the code | A small pure-Python library; the font prints every name, accents included. |
| Dimona client | requests for the calls, PyJWT and cryptography to sign the authentication with the private key | The same way DimonAPP V2 talks to the RSZ. |

## 4. Data and database management

The application stores highly confidential personal data (national register numbers and IBANs). Data handling is therefore GDPR-relevant and follows these rules:

- **Database:** Cloud SQL for PostgreSQL 16, one instance for acceptance and one for production, on the smallest machine type. The two never share an instance, so nothing done in acceptance can touch the production data.

- **Region:** europe-west1 (Belgium) for the database and its backups.

- **Network:** the Cloud Run service connects through Cloud Run's built-in Cloud SQL connection (a Unix socket backed by the Cloud SQL Auth Proxy); the instance has no authorised networks, so the database is never reachable from the public internet. Locally, the application connects over TCP to a PostgreSQL container.

- **Encryption:** Cloud SQL default encryption at rest and in transit. Application-level field encryption was considered and left out as overkill.

- **Backups:** automated Cloud SQL backups every night, kept in europe-west1, in acceptance as in production (the acceptance data is fictitious, but the cost is negligible and a restore can be tried there first). Production also has point-in-time recovery and deletion protection.

- **Data minimisation:** national numbers and IBANs live only in the workers table. They leave the database only where strictly needed: the IBAN in the payment export, the national number in Dimona calls and in the 281.27 / Belcotax output. They are never written to logs. An unexpected error shows a general message in the browser, never its technical details, and a database error never carries the values it was given into the logs or the page; a worker that cannot be saved gives a French message instead. The IBAN in the organisation details (section 7.7) is BMC's own account, not personal data.

- **Document storage:** every contract and qualification is backed by its original uploaded file. Files are stored unmodified (not parsed) in a private Google Cloud Storage bucket, one for acceptance and one for production (dimonapp-acc-documents, dimonapp-prod-documents), in europe-west1. The database only holds metadata and the object path. The bucket is not public; files are served to admins through the application only. The bucket is named by the setting STORAGE_BUCKET; the application reaches it as the service account of the Cloud Run service, without any key file. Without that setting (the local test environment) the files go to a local folder.

- **Test environment (local):** a throwaway PostgreSQL in Docker with fake data, on the developer's machine. It runs with the TEST label, so it makes no Dimona call. It is the test environment of section 3.2; there is none in GCP. Real data never leaves GCP.

## 5. Worker types and regimes

Exactly four worker types are supported. The type determines whether a Dimona is required, which legal limits apply and whether a fiche 281.27 is produced. Whatever the type, every worker needs a valid contract of that type and a valid qualification to perform an activity (section 7.3).

| **Worker type**              | **Dimona**   | **Legal limits**                                        | **Year-end output**               |
|------------------------------|--------------|---------------------------------------------------------|-----------------------------------|
| Vrijwilliger (volunteer)     | Not required | Compensation cap, no hours cap                          | None (no fiche)                   |
| Article 17 (verenigingswerk) | Required     | Hours per quarter and per year, annual compensation cap | Fiche 281.27 (PDF + Belcotax XML) |
| Flexi-jobber                 | Required     | Minimum 3 hours per activity, annual earnings cap       | Not in scope of this application  |
| Freelancer                   | Not required | None: unlimited hours and euros, never flagged          | None (invoices BMC)               |

A freelancer behaves like a volunteer on the mechanics: declares activities, has a rate per activity type, and confirming an activity triggers no Dimona call.

### 5.1 One-way status progression

A worker can only move up the hierarchy, never down. This is both a legal rule and BMC practice. The ladder is a rule the admin applies when changing a worker's type; the application documents it but does not enforce it in code.

- Allowed: volunteer to article 17, article 17 to flexi-job (and volunteer directly to flexi-job).

- Not allowed: any downgrade. The admin is responsible for not making such a change; the application does not refuse it.

- Limits are tracked independently per status. Moving up starts the worker on a fresh set of limits for the new status, whatever their usage under the previous one.

- A contract belongs to one worker type (section 7.3). After a change of type the worker can only declare again once a contract of the new type is on file; the contracts of the previous type stay on file but no longer count.

- Freelancer is a separate category outside this ladder. Changing a worker to or from freelancer is neither an upgrade nor a downgrade.

### 5.2 Activity types and compensation models

There are exactly two compensation models. Every activity type is tagged with one of them.

- **Hourly:** compensation = the worker's rate for that activity type multiplied by the hours entered.

- **Fixed price:** compensation = the worker's rate for that activity type, once per activity, regardless of the hours entered and regardless of the day it takes place. The worker still enters the hours; they are recorded but do not affect pay.

Variations in effort (such as route difficulty) are modelled as separate activity types rather than as modifiers: one activity type, one model, one rate. The only additions to that amount are the two supplements below.

| **Activity type** | **French label** | **Compensation model** | **Short description** | **Supplement** |
|---|---|---|---|---|
| Opening the gym (permanence) | Permanence | Fixed price | Not asked | None |
| BMC courses (leisure, provincial) | Cours BMC | Hourly | Not asked | None |
| Group course without instructor (schools) | Cours groupe sans mono | Hourly | Not asked | Group travel |
| Group course with instructor (groups, schools, associations, companies) | Cours groupe avec mono | Hourly | Not asked | Group travel |
| Route setting easy (4A to 5C) | Ouverture 4A - 5C | Fixed price | Mandatory | Rope supplement |
| Route setting medium (6A to 6C) | Ouverture 6A - 6C | Fixed price | Mandatory | Rope supplement |
| Route setting hard (7A and up) | Ouverture 7A et plus | Fixed price | Mandatory | Rope supplement |
| Route cleaning easy | Démontage facile | Fixed price | Optional | None |
| Route cleaning hard (ropes 9 to 14) | Démontage difficile (cordes 9 à 14) | Fixed price | Optional | None |

Nine activity types in total: three hourly and six fixed price. The same list is used everywhere an activity type appears: the create form, compensation sheets, authorisations and reports. The list follows the BMC timesheet, which the application replaces. One route is one activity: a worker who sets or cleans two routes on one day declares two activities. Giving stages is not an activity type in this version.

**Supplements.** A supplement is a fixed amount added to the compensation of one activity. It is never declared on its own: the worker ticks a box on the activity it belongs to. It adds no hours and no Dimona declaration of its own; the amount is part of the compensation of that activity, so it counts in every total, limit, payment and fiche like the rest of the compensation.

| **Supplement** | **French label** | **Offered on** | **Rule** |
|---|---|---|---|
| Group travel | Déplacement groupe | The two group course types | At most once per worker per day |
| Rope supplement | Supplément corde 9 à 14 | The three route setting types | For a route on ropes 9 to 14 |

Each supplement has a rate per worker on the compensation sheet (section 7.4), effective-dated like every other rate. Compensation of an activity = the amount of its model (hourly or fixed price) plus the supplement rate when the box is ticked.

## 6. Worker view

A minimal Streamlit application with four tabs.

### 6.1 Tab "Create activity"

- **Date:** date picker. The date must be today or later. Past dates are rejected: work cannot be declared retroactively. The date can be at most 3 months ahead (up to the same day of the month three months from today); later dates are rejected. For flexi-jobbers the RSZ adds a limit: a flexi-job can be declared at the earliest one month before the start of the quarter it falls in (work in January, February or March from 1 December on). The date picker of a flexi-jobber therefore stops at the end of the current quarter, or at the end of the next quarter once that quarter starts within a month, and never goes further than the 3 months.

- **Activity type:** one of the nine activity types of section 5.2.

- **Start time (flexi-jobbers only):** the time the activity starts, in steps of half an hour (17:00, 17:30 and so on). The RSZ requires a start and an end time in the Dimona declaration of a flexi-job; the end time is the start time plus the duration. Other worker types do not see this field.

- **Duration:** the time the activity will take, in whole hours (1, 2, 3 and so on; the RSZ only takes whole hours in a Dimona declaration). Always entered, also for fixed-price activities. The field opens on 1 hour.

- **Short description:** free text (for example which wall or sector), labelled "Description" in the form. The field is only shown when a route setting or a route cleaning ("Démontage") activity type is picked, on a row of its own over the full width of the form. Mandatory for the three route setting activity types, optional for the two route cleaning types. A route setting activity without a description is refused. The other activity types have no description.

- **Supplement:** a tick box carrying the name of the supplement, only shown when the picked activity type has one (section 5.2): "Déplacement groupe" on a group course, "Supplément corde 9 à 14" on a route setting activity. Not ticked by default. A group travel supplement is refused when the worker already has one on that day on a counted activity (section 12).

- For flexi-jobbers, a duration below the configured minimum hours per activity (section 7.7, 3 hours today) is refused.

- On submit, the backend runs the submission gate of section 8: valid contract, valid qualification, then the Dimona call where applicable.

- Only when every applicable check passes does the worker get a confirmation message. If any check fails, the worker gets an error message saying which one (invalid input, missing contract, missing qualification, or Dimona rejection).

### 6.2 Tab "Cancel activity"

- Works per month, like the Monthly overview: previous and next arrows to move between months, opening on the current month.

- Lists the worker's own non-cancelled activities of the selected month only, so the list stays short over time.

- A month without such an activity shows the note "Aucune activité à annuler pour ce mois." instead of an empty list.

- A worker may cancel any of them, past or future.

- Cancellation follows the flow in section 9.

### 6.3 Tab "Monthly overview"

- A table of the worker's activities for the selected month: date, type, short description, duration, supplement (its amount, empty without one), compensation (supplement included), Dimona status, cancelled yes or no.

- A month without activities shows the note "Aucune activité pour ce mois." instead of an empty table.

- Below the table, one overall total for the month: total hours and total compensation. No breakdown per activity type.

- Totals only include counted activities (section 12): cancelled and Dimona-rejected activities are excluded.

- Previous and next arrow buttons (arrow icons, no text) to move between months. Opens on the current month; the totals follow the selected month.

### 6.4 Tab "My authorisations"

- Read-only table of the worker's own contracts and qualifications: document type (a contract with its worker type, for example "Contrat (Article 17)"), covered activities, start date, end date, and a link to download the original file. The three course types are shown as the single clearance "Cours" and route setting and route cleaning as the single clearance "Ouverture de voies" (section 7.3), never per activity type.

- Every document has a status: "Valide", or "Expiré" once its end date has passed, so the worker sees at a glance which activities they are currently allowed to do. A document without an end date never expires; one that only starts later is shown as "Valide". Without any document the tab shows "Aucun contrat ni qualification enregistré.".

- Workers cannot upload, edit or delete documents; only admins can.

## 7. Admin console

Eight tabs, in this order: Dashboard, Monthly report, Activities, Workers, Authorisations, Compensation, Year-end fiches, Configuration (French names in section 3.4). The sections below follow the order in which they were specified, not the tab order.

### 7.1 Dashboard (landing page)

The first screen after admin login.

- **Monthly cost:** projected total cost of the counted activities (section 12) of the current month, across all workers.

- **Legal limit red flags:** every worker who has reached 90% or more of a limit for their current status is flagged (see section 10). Only limits of the current calendar year and of later years are shown: a flag of a past year disappears when the year is over. Flags warn only; nothing is blocked.

- **Pending Dimona warnings:** every activity whose Dimona status is pending is listed. After checking the declaration on the RSZ portal, the admin resolves it from the dashboard: either mark it "ok" and enter the Dimona declaration ID, or mark it "rejected".

- **Missing limits warning:** if any counted activity falls in a calendar year for which no limits, or only part of the limits (section 10), are configured, the dashboard shows "No limits configured for \<year\>" so the admin can enter that year's indexed values in the Configuration tab.

- **Expiring contract warnings:** every active worker whose contract ends within the next 30 days is listed with the worker type of the contract, the end date and the activities it covers, so a new contract can be arranged before the worker is blocked. Only contracts of the worker's current type count: a contract of another type does not let the worker declare. Contracts without an end date never trigger this warning.

- **Calendar of the month:** below the warnings, under the heading "Activités du mois", a calendar of the current month (Monday to Sunday) with the accepted activities only: not cancelled, with Dimona status "ok" or without Dimona. Pending, rejected and cancelled activities are left out. Each activity is a block on its day with the worker's name and, in bold on the right, the hours; neither the activity type nor the compensation is written. The colour of a block tells the activity type, explained in a legend that lists the types of the month: permanence green, courses in shades of blue, route setting from yellow to red with the grade, route cleaning in amber and dark red. On a narrow screen (a phone) the calendar becomes a list of the days with activities. A month without an accepted activity shows "Aucune activité acceptée pour ce mois.".

### 7.2 Worker management

- Create, edit and deactivate worker accounts.

- **Layout:** the list of workers, with three forms below it that fold open: "Ajouter un travailleur", "Modifier ou désactiver un travailleur" and "Définir le mot de passe d'un travailleur".

- Fields, all mandatory: first name, last name, national register number, IBAN, worker type, username, e-mail, login method (Google or local), and the postal address (street and number, postal code, municipality).

- The postal address is printed on the fiche 281.27 and is mandatory in the Belcotax file (section 7.6). Only Belgian addresses are supported (a postal code of four digits).

- The list of workers shows first name, last name, worker type, e-mail, IBAN and status. It is ordered by status (active first), then worker type (in the order of section 5), then first name; the worker dropdowns of the admin console follow the same order.

- In the create form, the eleven rate fields (nine activity types and two supplements) carry the name of the activity (for example "Ouverture 4A - 5C", "Démontage difficile"), without the unit; the compensation sheet (section 7.4) shows the model next to each rate. Each field opens on the standard BMC rate of section 7.4, which the admin changes where this worker differs. The forms of the tab carry no explanatory notes.

- The national register number is validated with its checksum on entry, so typos never reach the Dimona API.

- The IBAN is validated with its checksum (the standard modulo 97 check, any country) on entry, so typos never reach the payment file.

- For local accounts the admin sets the username and the password. A password has at least 10 characters. There is no forced password change at first login.

- Passwords are write-only for the admin: the admin can set or reset a worker's password at any time, but can never read it (it is stored only as a hash and never displayed, exported or logged). The "Set password" form has two masked fields (new password and confirmation), so the worker can type the new password themselves on the admin's screen: the admin signs in, opens the form for that worker, lets the worker enter the password, and saves. Workers cannot change their own password inside the application; they ask an admin.

- Worker type changes follow the one-way progression of section 5.1 (freelancer sits outside it). The admin applies this rule; the application does not check it.

- Deactivation: workers are never deleted (history and fiches must remain). An inactive worker cannot log in nor declare activities.

### 7.3 Authorisations tab (contracts and qualifications)

A worker can only perform an activity when two documents covering it are on file: a contract and a qualification (proof of onboarding). Both are must-haves. A qualification (fiche de formation) belongs to activities. A contract belongs to a worker type and to activities: an article 17 contract is not a flexi-job contract, so a contract only counts while the worker has the type it was signed for.

- **Layout:** a tab named "Authorisations". At the top, a dropdown to select a worker. Below it, a table with all of that worker's contracts and qualifications: document type (a contract with its worker type, for example "Contrat (Article 17)"), covered activities, start date, end date, upload date and a link to download the original file.

- **Upload:** an "Upload" button underneath the table reveals an upload form (a second section of the page).

Upload form fields, all mandatory except the end date:

- File (the original document, stored as-is, not parsed).

- Document type: contract or qualification.

- Worker type, for a contract only: one of the four worker types of section 5. The form opens on the worker's current type; another type can be chosen, for example to put the new contract on file before the worker's type is changed. A qualification has no worker type and the field is not shown for it.

- Covered activities: one or more of the nine activity types of section 5.2. One document can cover several activities. The form offers three choices, and tables show a clearance as one item: "Permanence"; "Cours", a single clearance for the three course types (BMC courses and the two group course types); and "Ouverture de voies", a single clearance for route setting and route cleaning (five activity types). Within a clearance the risk and the clearance are the same, and the types only differ to set the rate; a document therefore covers all types of a clearance or none. A supplement needs no clearance of its own.

- Start date.

- End date: optional; empty means valid indefinitely. In practice qualifications never have an end date, but the structure is kept identical for simplicity.

**Validity rule:** a document covers an activity when the activity type is in its covered list and the activity date is on or after the start date and, if an end date is set, on or before it. A contract must in addition be of the worker's type at the moment of the declaration.

- **Edit:** the admin picks a document in a dropdown below the table and uses the Edit button. The admin can correct the document type, the worker type of a contract, covered activities, start date and end date, and can replace the file.

- **Delete:** the same dropdown has a Delete button, with a confirmation step. Deleting removes the record and its stored file.

- **Documents in use are kept:** a document that an activity relied on is the evidence that the worker was allowed to do that work, so it is kept. A document is in use when an activity of the same worker was registered after the document was uploaded, has an activity type the document covers, and falls on a date the document covers; for a contract the worker type copied onto the activity must also be the contract's. Every registered activity counts, cancelled and Dimona-rejected ones included, as each passed the gate. When two documents cover the same activity, both are in use, as the application does not know which one the gate relied on. A document in use cannot be deleted, and only its end date can still be changed, to any date on or after the start date: the other fields and the file are greyed out, as is the Delete button, with the reason "Ce document a servi à déclarer des activités : il ne peut plus être supprimé, et seule sa date de fin peut encore être modifiée." An end date stops new declarations as a delete would. A document no activity relied on, for example one uploaded for the wrong worker, can still be corrected or deleted freely.

Editing or deleting an authorisation only affects activities declared afterwards. Activities already registered are immutable and stay valid; the gate is checked once, at declaration time.

### 7.4 Compensation sheets (versioned)

- Each worker has an individual compensation sheet: one rate per activity type and one per supplement (eleven rates). All eleven rates are entered when the worker is created, and a rate stays valid until a newer version replaces it, so a worker always has a rate for any activity they declare.

- The create form opens on the standard BMC rates below, taken from the BMC timesheet. They are defaults only: the admin can change every one of them, and the internal baremas that decide when a worker differs are out of scope. The standard rates are constants in the code; changing them needs a release.

| **Rate** | **Standard rate** |
|---|---|
| Permanence | 60,00 € per activity |
| Cours BMC | 18,00 € per hour |
| Cours groupe sans mono | 20,00 € per hour |
| Cours groupe avec mono | 40,00 € per hour |
| Déplacement groupe (supplement) | 25,00 € per activity |
| Ouverture 4A - 5C | 50,00 € per activity |
| Ouverture 6A - 6C | 60,00 € per activity |
| Ouverture 7A et plus | 70,00 € per activity |
| Supplément corde 9 à 14 (supplement) | 10,00 € per activity |
| Démontage facile | 15,00 € per activity |
| Démontage difficile (cordes 9 à 14) | 25,00 € per activity |

- The meaning of a rate follows the activity type's compensation model: an hourly rate for hourly activities, an amount per activity for fixed-price activities and for the two supplements. The sheet shows the model next to each rate so the admin knows which one they are entering.

- Rates are effective-dated. Changing a rate (for example after a promotion) adds a new version valid from a given date. Saving a version for a date that already has one replaces the amount of that version, so a typing error can be corrected.

- **Layout:** the sheet of the selected worker with the rates valid today, and two parts that fold open: "Nouvelle version de tarif" to add a version, and "Toutes les versions de tarif" with the full history.

- A new activity uses the rate valid on its activity date. Activities already declared keep their stored amount, even when a later rate version covers their date.

### 7.5 Monthly report and payment export

- A table with, per worker, the totals of the counted activities (section 12) of the selected month (hours, amount due), their current worker type and their IBAN, with the total to pay ("Total à payer") below it. A worker without counted activity in the month is left out; a month without any shows "Aucune activité comptabilisée pour ce mois.".

- The month is chosen with previous and next arrow buttons around the month name, as in the Monthly overview (section 6.3), opening on the current month.

- An export button produces a bulk payment file for Belfius Direct Net.

- Belfius accepts file payments for business customers in SEPA pain.001 (XML) and CSV (UTF-8) format; one file may contain several payment bulks. Target format: SEPA pain.001.

- The file is one message with one payment bulk (one debit on BMC's account): a SEPA credit transfer in euro to every worker of the report with an amount due, from the IBAN of BMC entered in the Configuration tab. The requested execution date is the day of the export; the communication reads "\<name of BMC\> \<month\> \<year\>". Names and communications only hold the characters SEPA accepts (accents are removed).

- The message version is pain.001.001.09 (ISO 20022, the version of the SEPA rulebooks since 2023), kept as a single constant and checked against the ISO schema stored with the code. The file is built directly as XML rather than with the "pain001" library, which is made for CSV input on the command line. Which version Belfius accepts for BMC's account is still to be confirmed (open item 1).

- The export button is disabled, with the reason shown, when nothing is due for the month or when BMC's name or IBAN is not configured.

### 7.6 Year-end fiche 281.27

- One button generates the fiches for every worker who held article 17 status during the selected year, and downloads everything in one go (zip).

- Output 1: one 281.27 PDF per worker, to hand to the worker. It holds the numbered boxes of the model of FOD Financiën, in French: number of the fiche, debtor (BMC), recipient with address, national register number, gross amount, and the hours per quarter with the sector.

- Output 2: one Belcotax-on-web XML file for electronic submission to FOD Financien: one sending with one declaration, BMC being both sender and debtor, in French.

- Totals are the sum of the compensation stored on each non-cancelled, Dimona-accepted article 17 activity of that year. "Held article 17 status" is read from the worker type copied onto each activity: a worker gets a fiche when at least one such activity exists in the year, also after moving on to flexi-job.

- Content of a fiche (Belcotax record 281.27): the total goes in zone 2.060 and, as everything is paid for work of the income year itself, in zone 2.063; amounts are in eurocents. The hours of the same activities go per quarter in zones 2.167 to 2.170, in hundredths of an hour. The sector (zone 2.099) is A, the sports sector. Compensation for earlier years, replacement income and reimbursed costs are not used.

- The fiches are numbered from 1 in the order of the workers' last names; a PDF carries the number its fiche has in the XML.

- The button is disabled, with the reason shown, while BMC's details are incomplete (section 7.7).

- The Belcotax XML schema is versioned per income year. The latest published version, and the target for this build, is belcotax-2025.xsd (income year 2025, Belcotax-on-web technical brochure version 1.0 of 5 December 2025), published by FOD Financiën under Belcotax-on-web, Documentation technique. The schema for income year 2026 (belcotax-2026.xsd) is expected around December 2026; the generator must be updated to it before the income year 2026 fiches are submitted. The schema version is a configuration constant, so each yearly update is a small, isolated change. The schema file is stored with the code and every generated file is checked against it. For an income year later than the stored schema, the file is still generated and the tab says which schema must replace it before submission.

- Legal deadline: end of February of the following year (28 February 2026 for income year 2025, according to the Belcotax-on-web brochure).

### 7.7 Configuration

- **Yearly legal limits:** per year and per worker type, the hours limit and euro limit per period. Limits are indexed every year, so they are configuration, never hard-coded. The compliance engine reads only from here. There is no "active year" setting: each activity is checked against the limits of the calendar year of its own date.

- **Organisation details:** BMC company number (ten digits) and the debtor details required for the 281.27 and the Belcotax file: name, street and number, postal code, municipality, contact person, telephone and contact e-mail. Also the IBAN of the account BMC pays from, used in the payment file (section 7.5). All of them are required and saved together. The limits and the organisation details each have their own save button.

Indicative values, to be confirmed against official indexed figures each year:

| **Worker type** | **Hours limit**                                                   | **Compensation limit**             |
|-----------------|-------------------------------------------------------------------|------------------------------------|
| Vrijwilliger    | None                                                              | About 1,800 to 1,900 euro per year |
| Article 17      | 150 hours per quarter, higher in the third quarter (450 per year) | About 7,700 to 8,000 euro per year |
| Flexi-jobber    | Minimum 3 hours per activity                                      | About 18,000 euro per year         |
| Freelancer      | None                                                              | None                               |

### 7.8 Activities

- A read-only view of the activities of every worker for one month, cancelled, rejected and pending ones included: date, worker, type, short description, duration, supplement, compensation (supplement included), Dimona status, cancelled yes or no. The columns are those of the worker's Monthly overview (section 6.3) with the worker's name added.

- Ordered by date, then by worker name. Previous and next arrow buttons move between months, as in the Monthly overview; the tab opens on the current month. A month without activities shows "Aucune activité pour ce mois.".

- No action can be taken from this tab and it shows no totals: payments are in the Monthly report (section 7.5). The table is interactive (sort, search, full screen, CSV download); its menus are in English, the one exception to the French interface (section 3.4).

## 8. Activity submission gate and Dimona flow

When a worker confirms an activity, the backend runs the checks below in order and stops at the first failure.

1.  Input validation: date not in the past and at most 3 months ahead (for flexi-jobbers also within the quarters the RSZ accepts), start time on the hour or half hour for flexi-jobbers, duration in whole hours, minimum duration for flexi-jobbers, short description present for route setting activities, no second group travel supplement on the same day. Failure: error message, nothing registered.

2.  Contract check: a valid contract (section 7.3) of the worker's type covers this activity type on this date. Failure: error message "no valid contract", naming the worker type, nothing registered.

3.  Qualification check: a valid qualification (section 7.3) covers this activity type on this date. Failure: error message "no valid qualification", nothing registered.

4.  The app computes the compensation with the rates valid on that date (rate x hours for hourly activities, the rate itself for fixed-price activities, plus the supplement rate when the box is ticked) and stores the result, the rate, the model and the supplement amount on the new activity.

5.  Vrijwilliger or freelancer: the activity is registered immediately with Dimona status "not applicable" and the worker gets a confirmation message. Done.

6.  Article 17 or flexi-jobber: the app POSTs the declaration to the Dimona API (reusing the Dimona integration of DimonAPP V2) and waits for the answer, showing a spinner. Responses typically take a few seconds. An article 17 declaration carries the date and the planned hours; a flexi-job declaration carries the date with the start and end time and no planned hours, as the RSZ requires. Both use joint commission XXX. A flexi-job that runs past midnight ends on the next day.

    **Several article 17 activities on one day.** The RSZ keeps at most one article 17 period per worker and day, and refuses a second Dimona IN for that day ("Période Dimona en double"). The first article 17 activity of a day therefore opens the period with a Dimona IN. Every later article 17 activity of that day sends a Dimona UPDATE of that period instead: its planned hours become those of all the day's non-cancelled activities with Dimona status "ok", plus the hours of the new activity. Steps 7 to 9 then apply to the answer to the update; a rejected update leaves the period as it was. While an article 17 activity of the same worker and day has Dimona status "pending", nobody knows the hours the RSZ holds for that day: the new activity is refused with an error message, nothing is registered and no call is made, until an admin has resolved the pending one (section 7.1). Flexi-job activities keep one declaration each (open item 8).

7.  Accepted: the activity is registered with status "ok" and the returned Dimona declaration ID (of the IN, or of the UPDATE for a later article 17 activity of the day). The worker sees a success message.

8.  Rejected: the activity is registered with status "rejected" and the worker sees a failure message with the reason returned by the API.

9.  No answer within 2 minutes: the activity is registered with status "pending", the worker sees a warning, and the activity appears in the pending list on the admin dashboard. The same happens when the RSZ cannot be reached or answers with a server error, also when that is known sooner. When the RSZ did receive the declaration but gave no verdict in time, the number it gave is kept in the Dimona message of the activity, so the admin can find the declaration on the RSZ portal; the declaration ID stays empty until the admin resolves the activity (section 7.1).

Key rule: the outcome shown to the user and stored on the record is always based on the actual API response (or its absence), never assumed.

## 9. Cancellation flow

1.  The worker selects an activity in the "Cancel activity" tab.

2.  Vrijwilliger or freelancer activity: it is marked cancelled. Done.

3.  No Dimona declaration ID on the record (rejected or pending): stop and warn the user. No API call is made.

4.  Declaration ID present: the app calls the Dimona API to cancel that declaration. An article 17 activity shares the Dimona period of its day with the worker's other article 17 activities of that day (section 8): while another non-cancelled activity of that day has Dimona status "ok", the app sends a Dimona UPDATE that lowers the planned hours of the period to theirs instead of cancelling it; the last accepted activity of the day cancels the period. While an article 17 activity of the same worker and day has Dimona status "pending", the cancellation stops with a warning and no API call is made.

5.  API confirms: the activity is marked cancelled, success message.

6.  API refuses, is unavailable or does not answer within 2 minutes: warning message to the user; the activity stays active.

Cancellation never edits or deletes the original activity data; it only sets the cancellation marker.

## 10. Compliance engine

- For each worker and their current status, the engine sums hours and compensation of counted activities (section 12) per period and per year, and compares them with the configured limits for that year (the calendar year of each activity's date).

- A year counts as configured only when every one of these limits is filled in: for vrijwilliger the euro limit per year; for article 17 the hours limit of each quarter (Q1 to Q4), the hours limit per year and the euro limit per year; for flexi-jobber the euro limit per year and the minimum hours per activity. If any of them is missing, the whole year is treated as not configured. Entering the complete set is the admin's responsibility.

- When an activity's year is not configured, the engine does not guess or reuse other years' values, raises no red flag for that year and does not block the activity; it raises the missing limits warning on the dashboard (section 7.1) instead.

- Planned (future) activities count, so problems are flagged before they happen.

- Results surface as red flags on the admin dashboard. The engine never blocks a declaration.

- Totals are tracked separately per status (section 5.1).

- Freelancers have no limits and never raise a red flag.

- Limitation: legal caps apply per worker across all organisations. The application only knows BMC activities and therefore tracks only BMC's share.

## 11. Data model

Eight tables, all simple one-to-many relations, plus two tables for the sign-in (11.9 and 11.10). Immutability is achieved by copying the compensation onto each activity, so an activity never depends on data that may change later.

### 11.1 workers

| **Field**                | **Type**       | **Notes**                                                            |
|--------------------------|----------------|----------------------------------------------------------------------|
| id                       | integer, PK    |                                                                      |
| first_name, last_name    | text           |                                                                      |
| national_register_number | text, unique   | Checksum-validated                                                   |
| iban                     | text           | Used for payment export                                              |
| worker_type              | enum           | vrijwilliger, article_17, flexi_job, freelancer; ladder of 5.1 applied by the admin, not enforced |
| username                 | text, unique   |                                                                      |
| email                    | text, unique   | Matched against the Google identity for Google accounts               |
| auth_method              | enum           | google or local                                                      |
| password_hash            | text, nullable | Local accounts only; never plain text                                |
| is_active                | boolean        | Deactivate instead of delete                                         |
| street, postal_code, city | text          | Belgian postal address, for the fiche 281.27 and Belcotax            |

### 11.2 admins

| **Field** | **Type**     | **Notes**                            |
|-----------|--------------|--------------------------------------|
| id        | integer, PK  |                                      |
| email     | text, unique | Google identity; Google sign-in only |
| is_active | boolean      |                                      |

### 11.3 activity_types (reference)

Small reference table seeded at deployment with the nine activity types and the two supplements of section 5.2 (eleven rows). Not editable from the UI in this version.

| **Field**            | **Type** | **Notes**                              |
|----------------------|----------|----------------------------------------|
| code                 | text, PK | For example route_setting_medium       |
| label                | text     | Shown in the UI                        |
| compensation_model   | enum     | hourly or fixed                        |
| description_required | boolean  | True for the three route setting types |
| supplement           | FK activity_types, nullable | The supplement offered on this activity type; empty when it has none, and on the supplements themselves |

### 11.4 compensation_rates

| **Field**     | **Type**          | **Notes**                                             |
|---------------|-------------------|-------------------------------------------------------|
| id            | integer, PK       |                                                       |
| worker_id     | FK workers        |                                                       |
| activity_type | FK activity_types | An activity type or a supplement                      |
| amount        | numeric           | Euro; per hour or per activity depending on the model; per activity for a supplement |
| valid_from    | date              | Newest version on or before the activity date applies |

### 11.5 activities (immutable)

| **Field**             | **Type**          | **Notes**                                                                                |
|-----------------------|-------------------|------------------------------------------------------------------------------------------|
| id                    | integer, PK       |                                                                                          |
| worker_id             | FK workers        |                                                                                          |
| worker_type           | enum              | Copied at declaration; drives per-status totals                                          |
| activity_date         | date              | Today or later at declaration                                                            |
| activity_type         | FK activity_types |                                                                                          |
| description           | text, nullable    | Mandatory for route setting types                                                        |
| duration_hours        | numeric           | Always recorded                                                                          |
| start_time            | time, nullable    | Flexi-job activities only: start of the activity, copied into the Dimona declaration     |
| compensation_model    | enum              | Copied at declaration: hourly or fixed                                                   |
| rate_applied          | numeric           | Copied at declaration; the rate of the activity type, without the supplement             |
| supplement_amount     | numeric           | Copied at declaration: the supplement rate when the box was ticked, otherwise 0          |
| compensation_amount   | numeric           | Computed at declaration, supplement included; never changes                              |
| dimona_status         | enum              | not_applicable, ok, rejected, pending; a pending status can be resolved once by an admin |
| dimona_declaration_id | text, nullable    | Needed for cancellation; for a later article 17 activity of the same day, the ID of its Dimona UPDATE |
| dimona_message        | text, nullable    | Rejection reason from the API                                                            |
| created_at            | timestamp         |                                                                                          |
| is_cancelled          | boolean           | Changes on cancellation                                                                  |

### 11.6 yearly_limits

| **Field**              | **Type**          | **Notes**                         |
|------------------------|-------------------|-----------------------------------|
| id                     | integer, PK       |                                   |
| year                   | integer           |                                   |
| worker_type            | enum              |                                   |
| period                 | text              | Q1 to Q4, or YEAR for annual caps |
| hours_limit            | numeric, nullable | Empty means no limit              |
| euro_limit             | numeric, nullable | Empty means no limit              |
| min_hours_per_activity | numeric, nullable | Flexi-jobbers: 3                  |

### 11.7 authorisations

One table for both contracts and qualifications, distinguished by a type field. Both share the same shape, except for the worker type that only a contract has.

| **Field**         | **Type**                     | **Notes**                               |
|-------------------|------------------------------|-----------------------------------------|
| id                | integer, PK                  |                                         |
| worker_id         | FK workers                   |                                         |
| document_type     | enum                         | contract or qualification               |
| worker_type       | enum, nullable               | The worker type of a contract; empty for a qualification |
| activity_types    | array of activity type codes | One or more covered activities          |
| start_date        | date                         |                                         |
| end_date          | date, nullable               | Empty means valid indefinitely          |
| file_path         | text                         | Object path in the Cloud Storage bucket |
| original_filename | text                         | Shown in the table and used on download |
| uploaded_at       | timestamp                    |                                         |

### 11.8 organisation_config

| **Field**       | **Type** | **Notes**                              |
|-----------------|----------|----------------------------------------|
| company_number  | text     | BMC enterprise number                  |
| name, address   | text     | Debtor details for 281.27 and Belcotax; address is the street and number |
| postal_code, city | text   | Debtor details for 281.27 and Belcotax |
| contact details | text     | Contact e-mail address, as required by Belcotax |
| contact_person, phone | text | As required by Belcotax             |
| iban            | text     | BMC's account, debtor of the payment file |

### 11.9 sign_in_failures

Wrong passwords of the local form, per typed username (R4.14). Rows older than 15 minutes are removed.

| **Field**       | **Type**    | **Notes**                                              |
|-----------------|-------------|--------------------------------------------------------|
| username_digest | text, PK    | SHA-256 of the typed username, never the username itself |
| n_failures      | integer     | Wrong passwords in a row                               |
| last_failed_at  | timestamp   | Time of the last wrong password                        |

### 11.10 last_actions

The last action of every signed-in account, for the 30 idle minutes (R4.13).

| **Field**    | **Type**     | **Notes**                     |
|--------------|--------------|-------------------------------|
| account_kind | text, PK     | admin or worker               |
| account_id   | integer, PK  | id in the admins or workers table |
| acted_at     | timestamp    | Time of the last action       |

## 12. Cross-cutting rules

- **Immutability:** once declared, an activity is written in stone. Only two things can change afterwards: the cancellation marker, and the Dimona fields of a pending activity when an admin resolves it (section 7.1).

- **Counted activity:** an activity that is not cancelled and whose Dimona status is not "rejected". Monthly totals, the monthly report, the dashboard cost, the compliance engine and the missing limits warning all use counted activities. The year-end fiche is stricter: only Dimona status "ok" (section 7.6).

- **Simplicity:** readable, testable code over clever abstractions.

- **Explicit feedback:** every action that calls the Dimona API ends with a clear success, failure or warning message.

- **Secrets:** Secret Manager in the cloud, git-ignored .env locally, never in the image or repository.

## 13. Out of scope

- Audit log of user and admin actions.

- Hard blocking of declarations that exceed legal limits (warnings only).

- Payment status tracking (paid versus outstanding).

- Application-level encryption of the national register number.

- Self-registration and self-service password reset.

- Volunteer nominative list export (can be added later from the same data).

- Parsing or reading the content of uploaded contracts and qualifications.

- Adding or editing activity types from the UI (the list is seeded; a change needs a release).

- Pay modifiers such as weekend or difficulty surcharges, other than the two supplements of section 5.2 (difficulty is modelled as separate activity types instead).

- The free lines of the BMC timesheet: "Commentaires et autres prestations" (a free amount) and "Achats et factures à rembourser" (reimbursements). They stay outside the application.

- Giving stages as an activity type.

## 14. Open items

| **\#** | **Item**                                                                                                                                                                                                                | **Owner** |
|--------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------|
| 1      | Confirm Belfius Direct Net file payment setup for BMC's business account and the exact accepted pain.001 version. The application builds pain.001.001.09; try a file generated in acceptance in Belfius Direct Net (upload without signing) before the first real payment. | BMC       |
| 2      | Confirm the official indexed limits for each worker type and year, and enter them in the Configuration tab each year. Note: the law counts article 17 hours per quarter (150, third quarter 285), not per quadrimester. | BMC       |
| 3      | Confirm the flexi-job declaration with a first accepted flexi-job in production. The Dimona client is ported from DimonAPP V2 (same authentication and calls; settings from environment variables, 2-minute limit, cancellation from the declaration ID), and the flexi-job declaration (start and end time, no planned hours, joint commission XXX) follows the rules of the RSZ, but the RSZ test service does not process flexi-job declarations, so acceptance cannot show an accepted one. | BMC       |
| 4      | Confirm the 30-day warning window for expiring contracts and the 90% threshold for legal limit flags.                                                                                                                   | BMC       |
| 5      | Decide whether a failed Dimona cancellation should also appear on the admin dashboard (today the worker only gets a warning and the activity stays active).                                                             | BMC       |
| 6      | Closed in version 4.5: five wrong passwords lock a username for 15 minutes (R4.14). | BMC       |
| 7      | Confirm the sector on the fiche 281.27 (zone 2.099): the application uses A, the sports sector. Compare a generated PDF with the official model of the fiche, and try the XML in the validation module of Belcotax-on-web before the first submission. | BMC       |
| 8      | Confirm whether the RSZ accepts several flexi-job periods for one worker on one day when their hours do not overlap. Until then every flexi-job activity is declared on its own; if the RSZ refuses the second one as a duplicate, flexi-jobs need the same update of the day's period as article 17 (section 8), with start and end times instead of hours. The RSZ test service does not process flexi-jobs (item 3), so this can only be checked in production. | BMC       |

## Appendix A. Requirements list

A numbered list of every requirement in this document, grouped by area. Each requirement has a stable ID for use in tickets and test cases; the last column refers to the section with the full explanation.

| **ID**  | **Requirement**                                                                                                                                                                                                                                                                                                                                                                                                                                              | **Section**  |
|---------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------|
| **R1**  | **Technology and platform**                                                                                                                                                                                                                                                                                                                                                                                                                                  | **3**        |
| R1.1    | The application shall be written in Python.                                                                                                                                                                                                                                                                                                                                                                                                                  | 3.1          |
| R1.2    | The Python project shall be managed with uv, with its metadata and dependencies in pyproject.toml and the uv.lock file committed.                                                                                                                                                                                                                                                                                                                            | 3.5          |
| R1.3    | The application code shall live in a src folder and the automated tests in a separate tests folder.                                                                                                                                                                                                                                                                                                                                                          | 3.5          |
| R1.4    | A Makefile shall provide at least make test (run the test suite) and make run (start the application locally).                                                                                                                                                                                                                                                                                                                                               | 3.5          |
| R1.5    | The user interface shall be built with Streamlit, as a tab-based web application.                                                                                                                                                                                                                                                                                                                                                                            | 3.1          |
| R1.6    | The application shall be packaged as a single Docker image used for all environments.                                                                                                                                                                                                                                                                                                                                                                        | 3.1          |
| R1.7    | The application shall run on Google Cloud Platform, on Cloud Run.                                                                                                                                                                                                                                                                                                                                                                                            | 3.1          |
| R1.8    | The application shall be publicly reachable over HTTPS and require authentication for every page.                                                                                                                                                                                                                                                                                                                                                            | 3.1          |
| R1.9    | Database access shall use SQLAlchemy 2.0 with the psycopg 3 driver.                                                                                                                                                                                                                                                                                                                                                                                          | 3.6          |
| R1.10   | Schema changes shall be managed with Alembic migrations, committed in the repository and applied automatically at container start-up.                                                                                                                                                                                                                                                                                                                        | 3.6          |
| R1.11   | Automated tests shall use pytest; database tests shall run against a PostgreSQL started by testcontainers, and the Dimona API shall be mocked in all tests.                                                                                                                                                                                                                                                                                                  | 3.6          |
| R1.12   | The Cloud Run service shall run with at most one instance.                                                                                                                                                                                                                                                                                                                                                                                                   | 3.6          |
| **R2**  | **Environments, configuration and secrets**                                                                                                                                                                                                                                                                                                                                                                                                                  | **3.2, 3.3** |
| R2.1    | There shall be three environments: test, acceptance and production. Acceptance and production shall each consist of its own Cloud Run service and its own Cloud SQL database in GCP; test shall run locally against a local PostgreSQL with fake data and shall not be deployed to GCP. | 3.2          |
| R2.2    | The environments shall be identical in schema and configuration shape; they shall differ only in the environment name and in injected configuration values (database connection, storage bucket, Dimona identifiers and key). | 3.2          |
| R2.3    | The test environment shall make no Dimona call (a fake service answers); acceptance shall call the RSZ Dimona test service; production shall call the live service. The service shall follow from the environment name alone. | 3.2          |
| R2.4    | The code shall read all configuration and secrets from environment variables; the environment name shall only decide the sidebar label and the Dimona service. | 3.3          |
| R2.5    | Locally, environment variables shall be loaded from a git-ignored .env file.                                                                                                                                                                                                                                                                                                                                                                                 | 3.3          |
| R2.6    | In GCP, the configuration shall be set on the Cloud Run service at deploy time, for acceptance and for production; every secret shall be injected from GCP Secret Manager. | 3.3          |
| R2.7    | No secret (Dimona certificate, API key, database password) shall be stored in the Docker image or the repository.                                                                                                                                                                                                                                                                                                                                            | 3.3          |
| **R3**  | **Data and storage**                                                                                                                                                                                                                                                                                                                                                                                                                                         | **4**        |
| R3.1    | Data shall be stored in Cloud SQL for PostgreSQL, one instance for acceptance and one for production.                                                                                                                                                                                                                                                                                                                                                                              | 4            |
| R3.2    | The database, its backups and the document bucket shall be located in europe-west1.                                                                                                                                                                                                                                                                                                                                                                          | 4            |
| R3.3    | The database shall only be reachable through Cloud Run's built-in Cloud SQL connection, never from the public internet.                                                                                                                                                                                                                                                                                                                                      | 4            |
| R3.4    | Automated Cloud SQL backups shall be enabled.                                                                                                                                                                                                                                                                                                                                                                                                                | 4            |
| R3.5    | National register numbers and IBANs shall only be stored in the workers table and shall never be written to logs.                                                                                                                                                                                                                                                                                                                                            | 4            |
| R3.6    | Uploaded contract and qualification files shall be stored unmodified in a private Google Cloud Storage bucket, one for acceptance and one for production; the database shall store only the object path and metadata.                                                                                                                                                                                                                                                                   | 4            |
| R3.7    | Local development shall use a throwaway PostgreSQL with fake data; real data shall never leave GCP.                                                                                                                                                                                                                                                                                                                                                          | 4            |
| R3.8    | The browser shall never show the technical details of an unexpected error, and a database error shall never carry the values it was given into the logs or the page. | 4            |
| **R4**  | **Accounts and authentication**                                                                                                                                                                                                                                                                                                                                                                                                                              | **2**        |
| R4.1    | Worker accounts and admin accounts shall be separate account types stored in separate tables.                                                                                                                                                                                                                                                                                                                                                                | 2            |
| R4.2    | A worker shall sign in with Google (BMC Workspace address) or with a local username and password.                                                                                                                                                                                                                                                                                                                                                            | 2            |
| R4.3    | An admin shall sign in with Google only.                                                                                                                                                                                                                                                                                                                                                                                                                     | 2            |
| R4.4    | Only admins shall create worker accounts; there shall be no self-registration.                                                                                                                                                                                                                                                                                                                                                                               | 2            |
| R4.5    | Local passwords shall be stored as a hash only, never in plain text.                                                                                                                                                                                                                                                                                                                                                                                         | 2            |
| R4.6    | A person holding both roles shall use two separate accounts.                                                                                                                                                                                                                                                                                                                                                                                                 | 2            |
| R4.7    | An inactive worker shall not be able to sign in.                                                                                                                                                                                                                                                                                                                                                                                                             | 7.2          |
| R4.8    | Google sign-in shall use Streamlit's built-in OIDC login (st.login, st.user, st.logout); the signed-in e-mail shall be matched against admins and active Google workers, and any other e-mail refused.                                                                                                                                                                                                                                                       | 3.6          |
| R4.9    | Local passwords shall be hashed with Argon2.                                                                                                                                                                                                                                                                                                                                                                                                                 | 3.6          |
| R4.10   | Streamlit's secrets.toml shall be generated at start-up from environment variables and never committed or built into the image.                                                                                                                                                                                                                                                                                                                              | 3.6          |
| R4.11   | At start-up, the Google address of the setting FIRST_ADMIN_EMAIL shall become the admin when the admins table is empty; with an admin present the setting shall change nothing. | 2            |
| R4.12   | A deactivated account shall be told at sign-in that it is deactivated: on the local form only when the password is right, after Google sign-in always; every other refusal of the local form shall give one general message. | 2            |
| R4.13   | A sign-in shall end 12 hours after it started, or after 30 minutes without any action of the account in any browser tab or device, whichever comes first, for Google and local sign-in alike; a local account shall then be told that its session has expired. | 2            |
| R4.14   | Five wrong passwords in a row for one username of the local form, each within 15 minutes of the one before, shall lock that username for 15 minutes, with the message "Trop de tentatives de connexion. Réessayez dans 15 minutes."; an unknown username shall be locked the same way, a successful sign-in or a new password set by an admin shall clear the count, and the typed username shall only be stored as a hash. | 2            |
| **R5**  | **Worker types and regimes**                                                                                                                                                                                                                                                                                                                                                                                                                                 | **5**        |
| R5.1    | The application shall support exactly four worker types: vrijwilliger, article 17, flexi-jobber and freelancer.                                                                                                                                                                                                                                                                                                                                              | 5            |
| R5.2    | Article 17 and flexi-jobber activities shall require a Dimona declaration; vrijwilliger and freelancer activities shall not.                                                                                                                                                                                                                                                                                                                                 | 5            |
| R5.3    | Worker type changes on the ladder vrijwilliger, article 17, flexi-jobber shall only be made upwards. This is a documented rule applied by the admin; the application shall not enforce it.                                                                                                                                                                                                                                                                   | 5.1          |
| R5.4    | Freelancer shall sit outside the ladder; changes to or from freelancer are neither upgrades nor downgrades.                                                                                                                                                                                                                                                                                                                                                  | 5.1          |
| R5.5    | Limit totals shall be tracked independently per worker status.                                                                                                                                                                                                                                                                                                                                                                                               | 5.1          |
| R5.6    | Freelancers shall have no hours or compensation limits.                                                                                                                                                                                                                                                                                                                                                                                                      | 5            |
| **R6**  | **Activity types and compensation**                                                                                                                                                                                                                                                                                                                                                                                                                          | **5.2, 7.4** |
| R6.1 | The application shall support nine activity types: opening the gym, BMC courses, group course without instructor, group course with instructor, route setting easy, route setting medium, route setting hard, route cleaning easy, route cleaning hard. | 5.2 |
| R6.2    | Each activity type shall have exactly one compensation model: hourly or fixed price.                                                                                                                                                                                                                                                                                                                                                                         | 5.2          |
| R6.3 | BMC courses and the two group course types shall be hourly; all other activity types shall be fixed price. | 5.2 |
| R6.4    | Hourly compensation shall equal the rate multiplied by the hours entered.                                                                                                                                                                                                                                                                                                                                                                                    | 5.2          |
| R6.5 | Fixed-price compensation shall equal the rate, once per activity, independent of hours and day; one route is one activity. | 5.2 |
| R6.6 | Each worker shall have one rate per activity type and one per supplement. | 7.4 |
| R6.7    | Rates shall be effective-dated; a new activity shall use the rate valid on its activity date, and activities already declared shall never be recalculated.                                                                                                                                                                                                                                                                                                   | 7.4          |
| R6.8 | Activity types and supplements shall be seeded at deployment and not editable from the UI. | 11.3 |
| R6.9 | The application shall support two supplements, each a fixed amount per worker added to the compensation of one activity: group travel on the two group course types and the rope supplement (ropes 9 to 14) on the three route setting types. | 5.2 |
| R6.10 | A supplement shall add no hours and no Dimona declaration of its own; its amount shall be part of the compensation of the activity in every total, limit, payment and fiche. | 5.2 |
| R6.11 | The group travel supplement shall be accepted at most once per worker per day, counting counted activities only. | 5.2, 6.1 |
| R6.12 | The rate fields of the worker create form shall open on the standard BMC rates of section 7.4, which the admin can change. | 7.2, 7.4 |
| **R7**  | **Worker view**                                                                                                                                                                                                                                                                                                                                                                                                                                              | **6**        |
| R7.1    | The worker view shall have four tabs: Create activity, Cancel activity, Monthly overview, My authorisations.                                                                                                                                                                                                                                                                                                                                                 | 6            |
| R7.2    | A worker shall only see their own data.                                                                                                                                                                                                                                                                                                                                                                                                                      | 6            |
| R7.3 | The create form shall ask for date, activity type and duration in hours; for flexi-jobbers only, the start time; only for route setting and route cleaning activity types, a short description on a full-width row of its own; and, only for an activity type with a supplement, a tick box for that supplement. | 6.1 |
| R7.4    | The activity date shall be today or later; past dates shall be refused.                                                                                                                                                                                                                                                                                                                                                                                      | 6.1          |
| R7.5    | The duration shall always be entered, in whole hours, also for fixed-price activities.                                                                                                                                                                                                                                                                                                                                                                                       | 6.1          |
| R7.6    | The short description shall be mandatory for route setting easy, medium and hard, optional for route cleaning easy and hard, and not asked for the other types. | 6.1          |
| R7.7    | For flexi-jobbers, a duration below the configured minimum hours per activity (3 hours today) shall be refused.                                                                                                                                                                                                                                                                                                                                              | 6.1          |
| R7.8    | The Cancel activity tab shall work per month, with previous and next arrows, opening on the current month.                                                                                                                                                                                                                                                                                                                                                   | 6.2          |
| R7.9    | The Cancel activity tab shall list the worker's non-cancelled activities of the selected month and allow cancelling any of them, past or future.                                                                                                                                                                                                                                                                                                             | 6.2          |
| R7.10 | The Monthly overview shall show the activities of a selected month with date, type, description, duration, supplement, compensation, Dimona status and cancelled flag. | 6.3 |
| R7.11   | The Monthly overview shall offer previous and next arrows and open on the current month.                                                                                                                                                                                                                                                                                                                                                                     | 6.3          |
| R7.12   | The Monthly overview shall show one total of hours and one total of compensation of the counted activities of the selected month.                                                                                                                                                                                                                                                                                                                            | 6.3          |
| R7.13   | The My authorisations tab shall show the worker's contracts and qualifications read-only, with file download, and mark expired documents.                                                                                                                                                                                                                                                                                                                    | 6.4          |
| R7.14   | An activity shall be declared at most 3 months ahead; later dates shall be refused. | 6.1          |
| R7.15   | For flexi-jobbers, the start time shall be entered in steps of half an hour and stored on the activity; the end time shall be the start time plus the duration. | 6.1          |
| R7.16   | A flexi-job activity shall be declared at the earliest one month before the start of the quarter it falls in; the date picker of a flexi-jobber shall follow that limit, and later dates shall be refused. | 6.1          |
| **R8**  | **Activity submission gate and Dimona**                                                                                                                                                                                                                                                                                                                                                                                                                      | **8**        |
| R8.1    | On submit, the backend shall check in order: input validation, valid contract, valid qualification, then Dimona where applicable, and stop at the first failure.                                                                                                                                                                                                                                                                                             | 8            |
| R8.2    | A failed input, contract or qualification check shall show an error naming the failed check and register nothing.                                                                                                                                                                                                                                                                                                                                            | 8            |
| R8.3 | The compensation shall be computed with the rates valid on the activity date, supplement included, and stored with the rate, the model and the supplement amount on the activity. | 8 |
| R8.4    | Vrijwilliger and freelancer activities shall be registered with Dimona status "not applicable" and confirmed immediately.                                                                                                                                                                                                                                                                                                                                    | 8            |
| R8.5    | For article 17 and flexi-jobber activities, the app shall POST the declaration to the Dimona API, reusing the Dimona integration of DimonAPP V2, and wait for the response. A flexi-job declaration shall carry the start and end time instead of the planned hours. | 8            |
| R8.6    | An accepted declaration shall register the activity with status "ok" and the returned declaration ID, and show a confirmation.                                                                                                                                                                                                                                                                                                                               | 8            |
| R8.7    | A rejected declaration shall register the activity with status "rejected" and the API reason, and show an error.                                                                                                                                                                                                                                                                                                                                             | 8            |
| R8.8    | If no response arrives within 2 minutes, the activity shall be registered with status "pending", the worker shall see a warning and the activity shall appear on the admin dashboard.                                                                                                                                                                                                                                                                        | 8            |
| R8.9    | A later article 17 activity of a worker on a day that already has an article 17 activity with Dimona status "ok" shall not send a new Dimona IN: the app shall send a Dimona UPDATE of that day's period, with the hours of all the day's non-cancelled "ok" activities plus its own, and register the activity from the answer as in R8.6 to R8.8. | 8 |
| R8.10   | While an article 17 activity of the same worker and day has Dimona status "pending", a new article 17 activity of that day shall be refused with an error message, without any Dimona call and without registering anything. | 8 |
| **R9**  | **Cancellation**                                                                                                                                                                                                                                                                                                                                                                                                                                             | **9**        |
| R9.1    | Cancelling a vrijwilliger or freelancer activity shall mark it cancelled immediately.                                                                                                                                                                                                                                                                                                                                                                        | 9            |
| R9.2    | If an article 17 or flexi-jobber activity has no Dimona declaration ID, cancellation shall stop with a warning and make no API call.                                                                                                                                                                                                                                                                                                                         | 9            |
| R9.3    | If a declaration ID exists, the app shall call the Dimona API to cancel it, or to lower the hours of the day's period as in R9.6. | 9 |
| R9.4    | The activity shall only be marked cancelled when the Dimona API confirms; otherwise, including after 2 minutes without an answer, the worker shall get a warning and the activity stays active.                                                                                                                                                                                                                                                              | 9            |
| R9.5    | Cancellation shall never delete or edit activity data other than the cancellation marker.                                                                                                                                                                                                                                                                                                                                                                    | 9            |
| R9.6    | Cancelling an article 17 activity while other non-cancelled article 17 activities with Dimona status "ok" remain on that day shall send a Dimona UPDATE lowering the hours of the day's period to theirs instead of cancelling the period; the activity shall only be marked cancelled when the API accepts the update (R9.4). | 9 |
| R9.7    | While an article 17 activity of the same worker and day has Dimona status "pending", cancelling an article 17 activity of that day shall stop with a warning and make no API call. | 9 |
| **R10** | **Admin dashboard**                                                                                                                                                                                                                                                                                                                                                                                                                                          | **7.1**      |
| R10.1   | The dashboard shall be the admin landing page.                                                                                                                                                                                                                                                                                                                                                                                                               | 7.1          |
| R10.2   | The dashboard shall show the projected total cost of the counted activities of the current month.                                                                                                                                                                                                                                                                                                                                                            | 7.1          |
| R10.3   | The dashboard shall flag every worker who has reached 90% or more of a legal limit for their status, in the current calendar year or a later one.                                                                                                                                                                                                                                                                                                                                                         | 7.1          |
| R10.4   | The dashboard shall list every activity with Dimona status "pending".                                                                                                                                                                                                                                                                                                                                                                                        | 7.1          |
| R10.5   | The admin shall be able to resolve a pending activity from the dashboard, either as "ok" with the Dimona declaration ID or as "rejected".                                                                                                                                                                                                                                                                                                                    | 7.1          |
| R10.6   | The dashboard shall show "No limits configured for \<year\>" when any counted activity falls in a year without a complete set of configured limits.                                                                                                                                                                                                                                                                                                          | 7.1          |
| R10.7   | The dashboard shall list every active worker whose contract of the worker's current type ends within the next 30 days.                                                                                                                                                                                                                                                                                                                                                                    | 7.1          |
| R10.8   | The dashboard shall show a calendar of the current month with the accepted activities only (not cancelled, Dimona "ok" or without Dimona), each as a block with the worker's name and hours, coloured by activity type.                                                                                                                                                                                                                                                                   | 7.1          |
| **R11** | **Worker management**                                                                                                                                                                                                                                                                                                                                                                                                                                        | **7.2**      |
| R11.1   | Admins shall be able to create, edit and deactivate worker accounts.                                                                                                                                                                                                                                                                                                                                                                                         | 7.2          |
| R11.2   | A worker record shall hold first name, last name, national register number, IBAN, worker type, username, e-mail, login method and postal address; all are mandatory when a worker is created or edited. | 7.2          |
| R11.3   | The national register number shall be validated with its checksum on entry.                                                                                                                                                                                                                                                                                                                                                                                  | 7.2          |
| R11.4   | For local accounts, the admin shall set the username and password; there shall be no forced password change at first login.                                                                                                                                                                                                                                                                                                                                  | 7.2          |
| R11.5   | Workers shall never be deleted; deactivation shall block sign-in and new activities while keeping history.                                                                                                                                                                                                                                                                                                                                                   | 7.2          |
| R11.6   | The admin shall be able to set or reset a worker's password at any time through a form with two masked fields, so the worker can type it themselves; the admin shall never be able to read a password.                                                                                                                                                                                                                                                       | 7.2          |
| R11.7   | Workers shall not be able to change their own password in the application.                                                                                                                                                                                                                                                                                                                                                                                   | 7.2          |
| R11.8   | The IBAN shall be validated with its checksum on entry. | 7.2          |
| R11.9   | A password set by the admin shall have at least 10 characters. | 7.2          |
| R11.10  | The admin shall enter a worker's Belgian postal address (street and number, postal code, municipality); a worker shall not be stored without one. | 7.2          |
| **R12** | **Authorisations (contracts and qualifications)**                                                                                                                                                                                                                                                                                                                                                                                                            | **7.3**      |
| R12.1   | A worker shall only be able to declare an activity when both a valid contract of the worker's type and a valid qualification covering that activity type on that date are on file.                                                                                                                                                                                                                                                                                                | 7.3          |
| R12.2   | The admin console shall have an Authorisations tab with a worker dropdown and a table of that worker's documents.                                                                                                                                                                                                                                                                                                                                            | 7.3          |
| R12.3   | An Upload button below the table shall open a form with file, document type, worker type (contracts only), covered activities, start date and optional end date.                                                                                                                                                                                                                                                                                                                           | 7.3          |
| R12.4   | One document shall be able to cover several activity types.                                                                                                                                                                                                                                                                                                                                                                                                  | 7.3          |
| R12.5   | A document shall be valid when the activity type is covered and the activity date is on or after the start date and, if set, on or before the end date.                                                                                                                                                                                                                                                                                                      | 7.3          |
| R12.6   | Admins shall be able to edit any field of a document and replace its file, except for a document in use (an activity relied on it), of which only the end date can be changed.                                                                                                                                                                                                                                                                                                                                                                                   | 7.3          |
| R12.7   | Admins shall be able to delete a document after confirmation, removing the record and its file, except for a document in use (an activity relied on it), which shall be kept.                                                                                                                                                                                                                                                                                                                                                              | 7.3          |
| R12.8   | Editing or deleting a document shall not affect activities already registered.                                                                                                                                                                                                                                                                                                                                                                               | 7.3          |
| R12.9   | Every contract and qualification shall be backed by an uploaded file; files shall not be parsed.                                                                                                                                                                                                                                                                                                                                                             | 7.3          |
| R12.10  | A contract shall carry exactly one worker type and a qualification none. A contract shall only count for the submission gate when its worker type is the worker's type at the moment of the declaration. | 7.3          |
| **R13** | **Monthly report and payments**                                                                                                                                                                                                                                                                                                                                                                                                                              | **7.5**      |
| R13.1   | The admin shall be able to view, per worker, the hours, amount due and IBAN of the counted activities of a selected month.                                                                                                                                                                                                                                                                                                                                   | 7.5          |
| R13.2   | An export button shall produce a SEPA pain.001 bulk payment file accepted by Belfius Direct Net.                                                                                                                                                                                                                                                                                                                                                             | 7.5          |
| **R14** | **Year-end fiche 281.27**                                                                                                                                                                                                                                                                                                                                                                                                                                    | **7.6**      |
| R14.1   | One button shall generate the fiches for every worker who held article 17 status in the selected year and download them in one zip.                                                                                                                                                                                                                                                                                                                          | 7.6          |
| R14.2   | The output shall contain one official 281.27 PDF per worker and one Belcotax-on-web XML file.                                                                                                                                                                                                                                                                                                                                                                | 7.6          |
| R14.3   | Fiche totals shall be the sum of the stored compensation of non-cancelled, Dimona-accepted article 17 activities of that year.                                                                                                                                                                                                                                                                                                                               | 7.6          |
| R14.4   | The Belcotax XML shall follow the schema of the selected income year; the initial target is belcotax-2025.xsd, to be updated to belcotax-2026.xsd once published and before the income year 2026 fiches are submitted.                                                                                                                                                                                                                                       | 7.6          |
| **R15** | **Configuration**                                                                                                                                                                                                                                                                                                                                                                                                                                            | **7.7**      |
| R15.1   | Admins shall be able to set, per year, per worker type and per period (Q1 to Q4 or YEAR), the hours limit, euro limit and minimum hours per activity.                                                                                                                                                                                                                                                                                                        | 7.7          |
| R15.2   | Limits shall never be hard-coded; the compliance engine shall read them only from configuration.                                                                                                                                                                                                                                                                                                                                                             | 7.7          |
| R15.3   | There shall be no "active year" setting; each activity is checked against the limits of the calendar year of its date.                                                                                                                                                                                                                                                                                                                                       | 7.7          |
| R15.4   | Admins shall be able to maintain BMC's company number and debtor details used for the 281.27 and Belcotax, and the IBAN BMC pays from, used in the payment file. | 7.7          |
| **R16** | **Compliance engine**                                                                                                                                                                                                                                                                                                                                                                                                                                        | **10**       |
| R16.1   | The engine shall sum hours and compensation of counted activities per worker, per status, per period and per year, including planned future activities.                                                                                                                                                                                                                                                                                                      | 10           |
| R16.2   | The engine shall compare these totals with the configured limits and raise red flags on the dashboard.                                                                                                                                                                                                                                                                                                                                                       | 10           |
| R16.3   | The engine shall never block a declaration.                                                                                                                                                                                                                                                                                                                                                                                                                  | 10           |
| R16.4   | When any required limit of a year is not filled in (section 10), the whole year counts as not configured: the engine shall not guess or reuse values, shall raise no flag for that year and shall raise the missing limits warning.                                                                                                                                                                                                                        | 10           |
| R16.5   | Freelancers shall never be flagged.                                                                                                                                                                                                                                                                                                                                                                                                                          | 10           |
| **R17** | **Cross-cutting rules**                                                                                                                                                                                                                                                                                                                                                                                                                                      | **12**       |
| R17.1   | A declared activity shall be immutable; only its cancellation marker and, when an admin resolves a pending declaration, its Dimona fields may change.                                                                                                                                                                                                                                                                                                        | 12           |
| R17.2   | A counted activity is one that is not cancelled and not Dimona-rejected; all totals except the year-end fiche shall use counted activities.                                                                                                                                                                                                                                                                                                                  | 12           |
| R17.3 | An activity shall store copies of the worker type, rate, compensation model, supplement amount and compensation amount valid at declaration. | 11.5 |
| R17.4   | Every action calling the Dimona API shall end with an explicit success, error or warning message.                                                                                                                                                                                                                                                                                                                                                            | 12           |
| R17.5   | The code shall favour readability and testability over abstraction.                                                                                                                                                                                                                                                                                                                                                                                          | 12           |
| **R18** | **Language, common layout, help and versioning**                                                                                                                                                                                                                                                                                                                                                                                                             | **3.4**      |
| R18.1   | The whole user interface shall be in French, including messages, errors, month names and number formatting; the only exception is the English menus of the interactive Activities table (R19.1). | 3.4          |
| R18.2   | Every page, including the login page, shall follow the DimonAPP V2 look: default Streamlit light theme, logoarriere logo at the top of a left sidebar, title "DimonAPP" with a subtitle, and tabs whose content starts with the tab name as heading.                                                                                                                                                                                                         | 3.4          |
| R18.3   | The application shall use two logos: favicon.png as browser favicon and as iOS home screen icon (served as apple-touch-icon), and logoarriere.png at the top of the sidebar inside the application.                                                                                                                                                                                                                                                          | 3.4          |
| R18.4   | The sidebar shall show, in this order and without an "About" heading: "DimonAPP" with a TEST, ACC or PROD label, a one-line explanation, "Connecté en tant que :" with "\<name\> - \<type\>" in bold on the next line (type: Volontaire, Article 17, Flexijob, Indépendant or Admin), the "Comment utiliser la DimonAPP ?" heading with the "Consulter les SOPs" button, and the "Se déconnecter" heading with the "Se déconnecter" button, without lines or extra space between the blocks. | 3.4          |
| R18.5   | The "Consulter les SOPs" button shall open https://www.brusselsmonkeysclimbing.com/sop in a new browser tab, in the worker view, the admin console and on the login page.                                                                                                                                                                                                                                                                                    | 3.4          |
| R18.6   | The environment label shall read "TEST" in the test environment, "ACC" in acceptance and "PROD" in production. | 3.4          |
| R18.7   | Every page shall show a full-width footer reading "V\<x.y.z\> - © \<current year\> Brussels Monkeys Climbing" with a link to www.brusselsmonkeysclimbing.com.                                                                                                                                                                                                                                                                                    | 3.4          |
| R18.8   | The version shall follow semantic versioning with 3.0.0 as the first release, be a pre-release of it raised with every pull request until that release (betas 3.0.0bN during the build, then release candidates 3.0.0rcN), be defined in one place in the code and be built into the Docker image, so the footer always shows the deployed version. | 3.4          |
| R18.9   | Withdrawn. The footer does not name the Dimona service: the service follows from the environment (R2.3), which the sidebar shows (R18.6). | 3.4          |
| R18.10  | The application shall serve a web app manifest, linked from the served page, that names it "DimonAPP", opens it on its start page without the browser bar and gives the favicon as a 192 x 192 and a 512 x 512 px maskable icon (a full orange square with the climber inside the central 80 %), so Android shows it on the home screen. | 3.4 |
| **R19** | **Activities overview** | **7.8** |
| R19.1   | The admin console shall have an Activities tab showing, for a month chosen with previous and next arrows, every activity of every worker in a read-only table with the columns of the Monthly overview and the worker's name. | 7.8 |
