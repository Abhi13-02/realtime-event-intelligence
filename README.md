# RealTime Event Intelligence

A multi-tenant, event-driven system that continuously crawls news sources (RSS, Reddit,
Hacker News), runs every article through an NLP pipeline, and pushes personalised topic
alerts to users over WebSocket, email and SMS.

**Live:** https://narrative.abhinavdev.online

- **Backend** — FastAPI (REST + WebSocket), Celery workers/beat, a Kafka pipeline consumer
- **Frontend** — Next.js 16 (App Router) with NextAuth
- **Data** — PostgreSQL 15 + pgvector (768-dim Sentence-BERT embeddings), Redis, Kafka (KRaft)
- **Everything runs in Docker**, in one Compose stack, on one virtual machine

---

## Table of contents

- [Run it locally](#run-it-locally)
- [Deployment & CI/CD](#deployment--cicd)
  - [The one-paragraph version](#the-one-paragraph-version)
  - [1. Where it runs — the VM](#1-where-it-runs--the-vm)
  - [2. How a visitor's request reaches the app](#2-how-a-visitors-request-reaches-the-app)
  - [3. What actually runs on the VM](#3-what-actually-runs-on-the-vm)
  - [4. The CI/CD pipeline](#4-the-cicd-pipeline)
  - [5. The deploy step, line by line](#5-the-deploy-step-line-by-line)
  - [6. The health check](#6-the-health-check)
  - [7. Where secrets and configuration live](#7-where-secrets-and-configuration-live)
  - [8. Database migrations](#8-database-migrations)
  - [9. When a deploy fails](#9-when-a-deploy-fails)
  - [10. Timeline of a single push](#10-timeline-of-a-single-push)
- [Operator cheat-sheet](#operator-cheat-sheet)
- [Known trade-offs](#known-trade-offs)

---

## Run it locally

```bash
cp .env.example .env     # fill in your keys
docker compose up --build
```

That starts the development stack only: Kafka, Postgres, Redis, the FastAPI backend, the
Celery worker/beat processes and the pipeline consumer. The frontend, the nginx proxy and
the Cloudflare tunnel are **not** started locally — they live behind a Compose profile
named `deploy` and only run in production (explained below).

---

# Deployment & CI/CD

This section is written for someone who has never seen the project before. No prior
knowledge of Docker, Cloudflare or GitHub Actions is assumed.

## The one-paragraph version

The whole application lives on a single Linux virtual machine as a set of Docker
containers. Nobody logs into that machine to deploy. Instead, **pushing to `main` on
GitHub is the deploy button**: GitHub Actions lints and builds the code, and if that
passes it opens an SSH connection to the VM, pulls the new commit, rebuilds the
containers, and then verifies the site is actually responding. The site is reachable at
a real domain even though the VM has **no web ports open to the internet** — a Cloudflare
Tunnel handles that.

```
  you: git push origin main
        │
        ▼
  ┌──────────────────────── GitHub Actions ────────────────────────┐
  │  backend-checks   (ruff lint + Python syntax compile)          │
  │  frontend-checks  (ESLint + full Next.js production build)     │
  │        │ both must pass                                        │
  │        ▼                                                       │
  │  deploy  ──SSH──▶  the VM                                      │
  └────────────────────────────────────────────────────────────────┘
                              │
                              ▼
            ┌──────────────── the VM (Ubuntu, ARM) ────────────────┐
            │  git reset --hard origin/main                        │
            │  docker compose up -d --build   (rebuild + restart)  │
            │  docker compose restart proxy                        │
            │  docker image prune -f                               │
            │  health check: is the site up? if not → fail loudly  │
            └──────────────────────────────────────────────────────┘
                              │
                              ▼
   internet ──▶ Cloudflare edge ──(tunnel)──▶ nginx ──▶ frontend / backend
```

---

## 1. Where it runs — the VM

Everything is deployed to **one virtual machine**: an Oracle Cloud "always free" ARM
instance running Ubuntu 22.04 (`aarch64`, 2 vCPU, ~12 GB RAM). It is a cloud VM, not a
VM running locally on the desktop — the desktop only holds the shortcut used to connect
to it.

**How to connect to it**

On the desktop there is a folder `VM-Control-Center` containing `ssh-24vm.bat`
(the "SSH 24" shortcut). Double-clicking it runs one command:

```bat
ssh 24vm
```

`24vm` is not a hostname — it is a **nickname** defined in `~/.ssh/config`, which maps it
to the VM's public IP, the `ubuntu` login user, and the private key file to authenticate
with. So the shortcut is just a convenience wrapper around a normal SSH login. The same
folder also holds shortcuts to the machine's monitoring tools (Cockpit, Netdata,
Uptime-Kuma), which are unrelated to this project but share the box.

The ARM CPU architecture matters in two places, and both are already handled:

- `Dockerfile` installs `build-essential` temporarily because `hdbscan`/`umap` publish no
  prebuilt ARM wheels and must be compiled from source, then removes the toolchain again
  to keep the image small.
- `frontend/Dockerfile` uses `node:22-alpine`, which is multi-architecture, and builds
  with webpack rather than Turbopack.

The project lives on the VM at `~/realtime-intel`, which is an ordinary `git clone` of
this repository. The VM also hosts a few unrelated side projects, which is why the
production Compose file goes out of its way not to occupy shared host ports.

---

## 2. How a visitor's request reaches the app

This is the part people usually find surprising: **the VM does not expose the website to
the internet at all.** No port 80, no port 443, no firewall hole. Instead a container
called `cloudflared` runs on the VM and dials *outward* to Cloudflare's network, holding
that connection open. When someone visits the site, Cloudflare accepts the request at its
own edge and sends it back down that already-open outbound connection.

> **Analogy:** rather than unlocking your front door and hoping only the right people walk
> in, the machine calls Cloudflare and keeps the phone line open. Traffic arrives through
> the call you placed. There is no door to pick.

This is a **named** Cloudflare Tunnel (config: `deploy/cloudflared/config.yml`), which
means it is registered against the Cloudflare account that owns `abhinavdev.online` and
keeps a stable hostname across restarts. Cloudflare manages the DNS records that point at
it. Three hostnames route into the stack; anything else gets a 404:

| Hostname | Goes to |
|---|---|
| `narrative.abhinavdev.online` | the app (canonical URL) |
| `abhinavdev.online` | the app (so the apex isn't a dead link) |
| `www.abhinavdev.online` | the app |
| anything else | `http_status:404` |

Once inside, the tunnel hands the request to **nginx** (`deploy/nginx.conf`), which is the
single entrypoint and splits traffic by URL path:

| Request path | Forwarded to | Why |
|---|---|---|
| `/v1/...` | `backend:8000` (FastAPI) | REST API **and** the WebSocket at `/v1/ws` — nginx is configured with `Upgrade`/`Connection` headers and a 1-hour read timeout so long-lived WebSocket connections are not cut off |
| everything else | `frontend:3000` (Next.js) | pages plus Next's own `/api` routes |

Because frontend and backend are served from **one** hostname, the browser never makes a
cross-origin request and no CORS configuration is needed.

The only host port the deployment actually publishes is `8090 → proxy:80`, and that is
used by the tunnel and by the CI health check — not by the public.

---

## 3. What actually runs on the VM

The stack is defined by **two** Compose files layered together, plus a profile:

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile deploy up -d --build
```

- **`docker-compose.yml`** — the base stack, shared with local development.
- **`deploy/docker-compose.prod.yml`** — a small production override that *removes* the
  host port publishing from `kafka`, `postgres`, `redis` and `backend`. In development
  those ports are exposed so you can attach DBeaver or `redis-cli` from your laptop. On
  the VM that would collide with the other projects on the box (there is already a native
  Redis on 6379), and it would needlessly expose infrastructure. Containers still reach
  each other by service name over the private Compose network.
- **`--profile deploy`** — three services are tagged `profiles: ["deploy"]`, so they exist
  only in production and never start during local development: `frontend`, `proxy` and
  `cloudflared`.

Containers currently running in production:

| Container | Role | Public? |
|---|---|---|
| `cloudflared` | outbound tunnel to Cloudflare | — |
| `proxy` | nginx, routes `/v1` → backend, `/` → frontend | `8090` on the VM only |
| `frontend` | Next.js production server (standalone build) | internal |
| `backend` | FastAPI: REST + WebSocket + the co-located alert service | internal |
| `celery-worker` | runs ingestion/notification tasks | internal |
| `celery-worker-discovery` | isolated worker for CPU-heavy UMAP/HDBSCAN clustering, so it can't starve ingestion | internal |
| `celery-beat` | the scheduler — enqueues tasks on a cron, executes nothing itself | internal |
| `pipeline-consumer` | reads `raw-articles` from Kafka, runs dedup → topic match → store → summarise → publish `matched-articles` | internal |
| `kafka` | message bus (KRaft mode, no Zookeeper) | internal |
| `postgres` | PostgreSQL 15 + pgvector, the only durable store | internal |
| `redis` | Celery broker (db 0) + WebSocket ticket store (db 1) | internal |
| `kafka-init` | one-shot: creates the three topics, then exits `0` | — |

Only Postgres has a named volume (`postgres_data`), so **only Postgres data survives**
a container rebuild. Kafka and Redis state is deliberately disposable.

---

## 4. The CI/CD pipeline

The pipeline is one GitHub Actions workflow: [`.github/workflows/ci-cd.yml`](.github/workflows/ci-cd.yml).

**When it runs**

- On every **push to `main`** → checks run, and if they pass, it deploys.
- On every **pull request into `main` or `ingestion`** → checks run, **no deploy**.

A `concurrency` group with `cancel-in-progress: true` means that if you push twice in
quick succession, the older run is cancelled. This prevents two deploys racing each other
onto the same machine.

**The three jobs**

| Job | Runs on | What it does | Blocks deploy? |
|---|---|---|---|
| `backend-checks` | GitHub's Ubuntu runner | `ruff check app` restricted to `E9,F63,F7,F82,F401` (syntax errors, undefined names, unused imports — the things that crash at runtime), then `python -m compileall app alembic` to prove every file parses | yes |
| `frontend-checks` | GitHub's Ubuntu runner | `npm ci`, `eslint app components lib --max-warnings 0`, then a **full `next build`** | yes |
| `deploy` | GitHub's Ubuntu runner, via SSH | ships the code to the VM (next section) | — |

Two deliberate choices worth explaining:

- **The lint gate is narrow on purpose.** Ruff is limited to error classes that indicate
  actual breakage. Style debt does not block a merge yet — a formatting nit should not
  stop a working fix from shipping.
- **The frontend is fully built in CI.** A Next.js type error or a bad import only shows
  up at build time, and finding that out *on the VM* would mean a broken deploy. Building
  it on the runner first turns a production outage into a red checkmark on the commit.
  (The build needs `AUTH_SECRET` to be set, so CI passes a throwaway value that is used
  for nothing but satisfying the build.)

The `deploy` job has three guards:

```yaml
needs: [backend-checks, frontend-checks]   # both checks must be green
if: github.event_name == 'push' && github.ref == 'refs/heads/main'
environment: production                    # secrets scoped to this environment
```

So a pull request can never deploy, a red build can never deploy, and only `main` deploys.

---

## 5. The deploy step, line by line

The job never copies build artifacts to the server. It opens an SSH session
(`appleboy/ssh-action`) using three GitHub secrets — `VM_HOST`, `VM_USER`, `VM_SSH_KEY` —
and runs this script **on the VM**:

```bash
set -e
cd ~/realtime-intel
git fetch origin main
git reset --hard origin/main
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile deploy up -d --build
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile deploy restart proxy
docker image prune -f
```

What each line does and why:

1. **`set -e`** — abort at the first failing command. Without it a failed build would be
   ignored and the job would report success while nothing changed.

2. **`git fetch` + `git reset --hard origin/main`** — the VM's checkout is forced to match
   `main` exactly. Not `git pull`: a pull can hit a merge conflict if someone edited a
   file directly on the server. `reset --hard` says "whatever is on the server, throw it
   away; GitHub is the truth." That makes the deploy *idempotent* — the same commit always
   produces the same server state. It is also why nothing secret is ever stored inside the
   repo directory on the VM (see the next section): a hard reset would destroy it.

3. **`docker compose ... up -d --build`** — rebuilds any image whose inputs changed and
   restarts the affected containers. Compose is smart enough to leave untouched services
   alone, so a frontend-only change does not restart Postgres or Kafka. `-d` detaches so
   the SSH session can end. The step is given a **40-minute timeout**, because on 2 ARM
   cores a from-scratch backend build has to compile native dependencies and bake the
   ~90 MB Sentence-BERT model into the image.

4. **`restart proxy`** — the non-obvious one. nginx resolves the IP addresses of
   `backend` and `frontend` **once, at startup**. When those containers are recreated they
   get new IPs on the Docker network, and nginx keeps forwarding to the old, dead
   addresses — the site would serve `502 Bad Gateway` even though every container is
   healthy. Bouncing the proxy forces a fresh DNS lookup. This line is the fix for a real
   outage, not boilerplate.

5. **`docker image prune -f`** — deletes the now-untagged previous image layers. On a
   free-tier disk, a few weeks of daily deploys will otherwise fill the volume and the
   next build fails with "no space left on device".

---

## 6. The health check

A deploy that "succeeded" but left the site down is worse than a failed one, so a second
SSH step verifies the result. It polls for **up to 5 minutes** (30 attempts, 10s apart)
and requires *both* layers to answer `200`:

```bash
curl http://localhost:8090/login                  # through nginx → Next.js
docker exec ...backend-1 python -c "...:8000/"    # FastAPI directly, inside the container
```

Checking both is intentional: the frontend alone could return `200` from a cached page
while the API is dead, and the API alone says nothing about whether nginx is routing
correctly. The retry loop exists because containers need time — Postgres has to accept
connections, Alembic migrations have to run, Kafka takes 20–30 seconds to become healthy.

If the loop expires, the step prints the last 30 lines of backend logs into the Actions
output and exits `1`, turning the run red. **You get the diagnostic without SSHing in.**

---

## 7. Where secrets and configuration live

Nothing sensitive is in the repository. Configuration is split three ways by *who needs it*:

| What | Where it lives | Why there |
|---|---|---|
| `VM_HOST`, `VM_USER`, `VM_SSH_KEY` | GitHub → Settings → Environments → **production** | Only GitHub Actions needs them, and scoping to an environment means a workflow on another branch can't reach them |
| App secrets: DB password, `AUTH_JWT_SECRET`, `GROQ_API_KEY`, Reddit, Twilio, SMTP, NewsAPI… | `~/realtime-intel/.env` **on the VM**, mode `600` | Git-ignored and created once by hand. Compose loads it automatically into every container via `env_file` |
| Cloudflare tunnel credentials | `~/.cloudflared/realtime-intel.json` on the VM, mounted read-only into the container | Deliberately kept **outside** the repo directory so `git reset --hard` can never delete or expose it |

`.env.example` documents every required variable name with no real values — that is the
file to copy when setting up a new machine.

---

## 8. Database migrations

There is no separate migration step in the pipeline, and that is by design. The backend
image's entrypoint (`docker-entrypoint.sh`) runs on **every** container start:

```bash
alembic upgrade head          # apply any pending migrations
exec uvicorn app.main:app ... # then become the web server
```

So a deploy that includes a new migration applies it automatically before the API begins
serving. `exec` replaces the shell with uvicorn so Docker's `SIGTERM` reaches uvicorn
directly and shutdowns stay graceful.

The trade-off to be aware of: migrations must be **backwards compatible**, because for a
few seconds during a deploy the old container may still be serving against the new schema.
Additive changes (new nullable column, new table) are safe; destructive ones (dropping or
renaming a column in one step) are not, and should be split across two deploys.

---

## 9. When a deploy fails

| Failure | What happens | What to do |
|---|---|---|
| Lint or frontend build fails | `deploy` never starts; the VM is untouched and still serving the previous version | Fix and push again |
| `git reset` / build fails on the VM | `set -e` stops the script; the run goes red | Read the Actions log; the previous containers are usually still running |
| Health check times out | Run goes red, backend logs are printed in the Actions output | Read the logs, fix forward, push |

There is **no automatic rollback**. Recovery is either "fix forward" (push a corrected
commit) or a manual revert:

```bash
git revert <bad-commit> && git push origin main      # preferred — keeps history honest
```

or, to restore service immediately from the VM itself:

```bash
ssh 24vm
cd ~/realtime-intel
git reset --hard <last-good-commit>
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile deploy up -d --build
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile deploy restart proxy
```

Note that a manual reset will be undone by the next push to `main`, since the deploy
always forces the VM back to `origin/main`.

---

## 10. Timeline of a single push

| Stage | Roughly |
|---|---|
| `backend-checks` (pip install + ruff + compileall) | ~1 min |
| `frontend-checks` (npm ci + eslint + next build) | ~2–4 min, runs in parallel with the above |
| SSH + `git reset` | seconds |
| `docker compose up --build` | seconds when nothing changed; **many minutes** when `requirements.txt` or the `Dockerfile` changes and native ARM deps must recompile |
| `restart proxy` + `image prune` | seconds |
| Health check | 10s in the good case, up to 5 min before it gives up |

A typical code-only change is live in **3–6 minutes**. A dependency change can take 20+.

---

## Operator cheat-sheet

All commands run on the VM after `ssh 24vm` (or by double-clicking `ssh-24vm.bat`).
The Compose flags are long, so it helps to define them once per session:

```bash
cd ~/realtime-intel
C="docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile deploy"

$C ps                          # what is running, and is it healthy
$C logs -f backend             # follow backend logs
$C logs --tail 100 pipeline-consumer
$C restart backend             # restart one service
$C restart proxy               # fixes 502s after containers were recreated
$C up -d --build               # manual deploy (same command CI runs)

docker exec -it realtime-intel-postgres-1 psql -U <user> -d <db>
docker stats --no-stream       # CPU/RAM per container
df -h                          # disk — watch this, free tier is small
```

Checking the site end to end:

```bash
curl -I http://localhost:8090/login          # through nginx, on the VM
curl -I https://narrative.abhinavdev.online  # through Cloudflare, from anywhere
```

---

## Known trade-offs

Stated plainly, because a reader should know where the edges are:

- **Single VM, single instance of everything.** No load balancer, no replicas. The VM is
  the single point of failure, and a deploy causes a few seconds of downtime rather than a
  zero-downtime rolling swap. This matches the project's stage, not its stated 99.9%
  uptime target.
- **The backend runs with the source bind-mounted (`./:/app`) and `uvicorn --reload`**,
  which is a development convenience carried into production. It works — `git reset` puts
  the new code on disk and the container sees it — but it means the running code comes
  from the host checkout rather than purely from the built image, and `--reload` costs a
  file watcher. Hardening this would mean dropping the mount in the production override
  and running uvicorn without `--reload`.
- **No automated tests in the pipeline.** `tests/` holds benchmarks and evaluation
  scripts, not a suite CI can gate on. The pipeline currently proves the code *builds*,
  not that it *behaves*.
- **No automatic rollback** — see [section 9](#9-when-a-deploy-fails).
- **Kafka/Redis state is not persisted.** Acceptable here (the system is designed to
  tolerate stale/lost in-flight messages), but worth knowing before assuming a restart is
  free.
