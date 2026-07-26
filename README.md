# RoleBricks

EmotionOS turns an open-ended situation into a persistent, voice-first scene with up to three AI characters. Users describe a scenario, review the generated Blueprint, approve the cast, and enter a researched scene with durable memory and expressive speech.

## Product Flow

1. Describe any situation.
2. Review the versioned Blueprint: role, objective, setting, pressure, and proposed cast.
3. Select one to three characters.
4. Confirm before any research or voice spend begins.
5. Review evidence and distinct voice samples.
6. Enter the scene, interact, pause, and resume with persistent memory.

Real public people are supported as clearly labelled public-information practice simulations. RoleBricks uses an original synthetic voice and never presents the agent as the real person.

## Runtime Architecture

- Shared static scene UI, FastAPI APIs, and a Jinja-only private admin view
- Lakebase Postgres for operational scene state
- Delta tables and AI Search for scoped character memory
- Databricks Foundation Model APIs for scene compilation
- OpenAI Responses API for fresh public research
- Adaptive speech routing across Sarvam, OpenAI, and a Hugging Face Space
- MLflow tracing with dialogue and private memories excluded
- Bounded queues, reusable prepared agent packs, and a strict three-character MVP limit
- Protected admin observability at `/admin` using the Databricks forwarded user email

No model weights or local GPU runtime are shipped with the Databricks App. The Hugging Face inference source remains in `hf_space/` and is deployed separately.

## Run Locally

Use Python 3.11:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe run.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Local defaults use deterministic rule compilation, no web research, SQLite, and database retrieval. Add API keys to `.env` to exercise voice providers.

## Databricks Deployment

Prerequisites:

- Databricks CLI 1.4 or newer
- Workspace URL
- Existing serverless SQL warehouse ID
- Available chat-capable Foundation Model endpoint
- OpenAI, Sarvam, and Hugging Face credentials

Authenticate:

```powershell
databricks auth login --host https://your-workspace.cloud.databricks.com
databricks current-user me
```

Create secrets interactively:

```powershell
databricks secrets create-scope emotionos-worlds
databricks secrets put-secret emotionos-worlds openai-api-key
databricks secrets put-secret emotionos-worlds sarvam-api-key
databricks secrets put-secret emotionos-worlds hf-token
```

Run `databricks/sql/bootstrap.sql` once in the SQL editor. Then deploy:

```powershell
$env:DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
$env:BUNDLE_VAR_sql_warehouse_id="your-warehouse-id"
$env:BUNDLE_VAR_foundation_model_endpoint="your-chat-endpoint"

databricks bundle validate -t dev --strict
databricks bundle plan -t dev
databricks bundle deploy -t dev
databricks bundle run -t dev scene_memory_pipeline
databricks bundle run -t dev emotionos
databricks bundle summary -t dev
```

Databricks App OAuth supplies workspace credentials automatically. Personal Databricks tokens do not belong in source files or App secrets.

## Public Vercel Gateway

The judge-facing UI can run on Vercel while the Databricks App stays private. Vercel serves `emotionos/app/public` and the server-only `api/gateway.js` function authenticates only allowlisted `/api` requests with a dedicated Databricks service principal.

Required Vercel Production environment variables:

- `DATABRICKS_HOST`: workspace URL, for example `https://dbc-...cloud.databricks.com`
- `DATABRICKS_APP_URL`: deployed `https://...databricksapps.com` URL
- `DATABRICKS_CLIENT_ID`: dedicated gateway service principal application ID
- `DATABRICKS_CLIENT_SECRET`: its OAuth secret, stored as a sensitive Vercel variable

Grant that service principal `CAN USE` on the Databricks App. Never expose these values through browser-prefixed variables or source files. The public gateway intentionally excludes `/admin`, suppresses the global scene list, applies bounded request limits, and caches only the short-lived OAuth access token. Recent scene IDs are kept in each browser so judges can resume their own scenes without seeing another visitor's list.

After the Vercel production deployment is healthy, add `rolebricks.aman-chauhan.co.in` to that Vercel project. Because GoDaddy remains the DNS provider, add only the exact `rolebricks` CNAME target shown by Vercel; do not change the apex, `www`, mail, or nameserver records.
## Configuration

- `.env.example`: local settings and provider keys
- `app.yaml`: deployed runtime environment and resource mappings
- `databricks.yml`: Lakebase, pipeline, AI Search, MLflow, volume, secrets, and App
- `databricks/sql/bootstrap.sql`: initial Unity Catalog schema and Delta tables

The production voice router selects exactly one provider before synthesis. It does not switch providers after a request fails.

## Verification

```powershell
.\.venv\Scripts\python.exe -m compileall -q emotionos migrations tests
node --check emotionos\app\public\static\js\worlds.js
npm run test:gateway
.\.venv\Scripts\python.exe -m pytest -q
```

The acceptance suite covers unseen scenarios, approval-before-spend, the three-character cap, version conflicts and reverts, preparation recovery, voice samples, scene turns, durable memory, and playable audio.

## Primary API

- `POST /api/worlds/draft`
- `PATCH /api/worlds/{id}/blueprint`
- `POST /api/worlds/{id}/revert`
- `POST /api/worlds/{id}/confirm`
- `POST /api/worlds/{id}/enter`
- `POST /api/worlds/{id}/turns`
- `POST /api/worlds/{id}/pause`
- `POST /api/worlds/{id}/resume`
- `POST /api/worlds/{id}/complete`
- `GET /ready`
- `GET /api/admin/overview` (admin only)
