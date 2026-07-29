# ANTS Backend — Deployment & CI/CD Setup Guide

This document covers how the backend (`ant-core-system`, branch `main-v2`) got
deployed to AWS EC2, and how the CI/CD pipeline works. Written for anyone
joining the project who needs to understand, review, or reproduce this setup.

**Live backend:** `https://ants.thihaeung.com`
**Server:** AWS EC2 `t3.small`, Ubuntu, IP `54.254.154.179`
**Repo:** `github.com/Morrowga/ant-core-system`, working branch `main-v2`

---

## Architecture Overview

One EC2 instance runs the entire backend stack via Docker Compose:

| Service | Role |
|---|---|
| `db` | Postgres 16 + pgvector, internal only (no host port published) |
| `redis` | Celery broker/backend, internal only |
| `api` | FastAPI app (uvicorn), runs migrations on startup, internal only |
| `worker` | Celery worker (certificates, invoices, background jobs) |
| `beat` | Celery beat (scheduled tasks) |
| `caddy` | Reverse proxy + automatic HTTPS (Let's Encrypt), the **only** public entry point |

Caddy is the only service with published ports (`80`/`443`). Everything else
talks over the internal Docker network by service name (`api`, `db`, etc.),
not `localhost`.

Deployment is **continuous delivery**, not continuous deployment: pushing
code only runs tests automatically. Actually deploying to the server requires
a manual click of "Run workflow" on GitHub — nothing touches the live server
just from a push.

---

## Part 1 — One-Time EC2 Server Setup

### 1.1 Install Docker

**Known gotcha:** this instance runs Ubuntu 26.04 ("resolute"), a release too
new for Docker's official repos to have packages for yet. The official
`get-docker.sh` convenience script also fails for the same reason. The fix is
to manually point the apt repo at the previous LTS codename (`noble`, 24.04)
instead of letting it auto-detect — Docker's engine packages work fine on a
newer Ubuntu even when built for the prior LTS.

```bash
# Clean up any partial/failed attempts first
sudo rm -f /etc/apt/sources.list.d/docker.list /etc/apt/keyrings/docker.gpg

# Prerequisites
sudo apt update
sudo apt install -y ca-certificates curl gnupg

# Docker's GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Repo, hardcoded to "noble" -- NOT auto-detected (would resolve to
# "resolute", which Docker doesn't have packages for)
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu noble stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Let your user run docker without sudo
sudo usermod -aG docker $USER
```

**Log out and back in** (or `newgrp docker`) for the group membership to
apply, then confirm:
```bash
docker --version
docker compose version
```

> If you're setting this up on a normal, already-supported Ubuntu LTS
> (22.04/24.04), skip the codename override — the standard official install
> script (`curl -fsSL https://get.docker.com | sudo sh`) will just work.

### 1.2 Clone the repo

```bash
git clone -b main-v2 https://github.com/Morrowga/ant-core-system.git ~/ants-backend
cd ~/ants-backend
```

> This was later switched from HTTPS to SSH (see Part 3.3) so the server can
> pull without interactive credentials — if cloning fresh today, you can
> clone via SSH directly instead and skip that later step.

### 1.3 Create the production `.env`

This file holds real secrets and is **never committed to git** — create it
directly on the server:
```bash
nano .env
```

Key things that must be **real values**, not placeholders, or the
corresponding feature silently fails:
- `ENV=production`, `DEBUG=false` (not `local`/`true` — this is public-facing)
- `DATABASE_URL` / `DATABASE_URL_SYNC` → point at `db:5432` (the Docker
  service name, not `localhost`, since this runs inside the same Compose
  network)
- `REDIS_URL` / `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` → point at
  `redis:6379/*`
- `JWT_SECRET_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
  `STRIPE_PRICE_HR`, `STRIPE_PRICE_WAREHOUSE`, `OPENAI_API_KEY` — real values
- `SMTP_*` — no default in Settings, required regardless of whether the demo
  touches email; a leftover placeholder like `your_app_password_here` will
  cause silent failures wherever SMTP is used
- `FRONTEND_URL` — **set this only after the frontends are deployed**
  (Part 4); until then, a placeholder like `http://localhost:3000` is fine
  short-term but must be updated + containers restarted once real frontend
  URLs exist, since this drives CORS

### 1.4 Add the Firebase credentials file

`FIREBASE_CREDENTIALS_PATH=app/firebase-service-account.json` is gitignored
(a secret), so it must be copied up manually from wherever it lives locally
— **run this from your own machine**, not the server:
```bash
scp -i /path/to/your-ec2-key.pem \
  path/to/firebase-service-account.json \
  ubuntu@ants.thihaeung.com:~/ants-backend/app/firebase-service-account.json
```
This file needs to exist **before** the Docker image is built, since it gets
baked into the image, not mounted live.

### 1.5 DNS — point the subdomain at this server

In Route 53 (or wherever the domain's DNS is managed):
- **Record name:** `ants` (for `ants.thihaeung.com`)
- **Record type:** `A`
- **Value:** the EC2 instance's public IP (`curl -s ifconfig.me` on the
  server to confirm)

Verify it resolves before continuing:
```bash
dig ants.thihaeung.com +short
```

### 1.6 Security group

Confirm inbound rules allow, from `0.0.0.0/0`:
- **22** (SSH)
- **80** (HTTP — Caddy needs this briefly even for HTTPS, to complete the
  Let's Encrypt certificate challenge)
- **443** (HTTPS)

### 1.7 Caddyfile

Already in the repo at `~/ants-backend/Caddyfile`, pointed at the real
subdomain:
```
ants.thihaeung.com {
	reverse_proxy api:8000
}
```

---

## Part 2 — First Manual Deploy

**Deploy manually once before trusting automation with it** — if the
server isn't fully ready (Docker not installed, `.env` missing, DNS not
propagated), the automated CI/CD deploy job would just fail identically.

```bash
cd ~/ants-backend
docker compose -f docker-compose.prod.yml up -d --build
```

### Known gotcha: migration failure on `sso_codes`

The first deploy attempt hit a real bug: Alembic's own tracking
(`alembic_version`) can end up in an inconsistent state (table physically
created, but not recorded as applied) — likely from a container getting
killed mid-migration (the `t3.small`'s 2GB RAM is genuinely tight running 6
containers at once). This caused an infinite restart loop, since the
`api` container's startup command re-runs `alembic upgrade head` every
time it starts.

**If this happens again:**
```bash
# Stop everything, wipe the Postgres volume for a truly clean slate
sudo docker compose -f docker-compose.prod.yml down -v
sudo docker compose -f docker-compose.prod.yml build api   # important: rebuilds
                                                            # so any code fix
                                                            # actually takes effect
sudo docker compose -f docker-compose.prod.yml up -d db redis
sleep 5
sudo docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
```

Verify success before bringing up the rest of the stack:
```bash
sudo docker compose -f docker-compose.prod.yml run --rm api alembic current
sudo docker compose -f docker-compose.prod.yml run --rm api alembic heads
# both should print the SAME revision ID
```

Then bring up everything:
```bash
sudo docker compose -f docker-compose.prod.yml up -d --build
sudo docker compose -f docker-compose.prod.yml ps   # all 6 should show "Up"
```

### Verify Caddy actually got a certificate
```bash
sudo docker compose -f docker-compose.prod.yml logs caddy --tail=30
```
Look for `"certificate obtained successfully"`.

### Verify end-to-end, from your own machine (not the server)
```bash
curl -I https://ants.thihaeung.com/docs
```
Should return `HTTP/2 200` with `server: uvicorn` and `via: 1.1 Caddy`.

### Seed demo data
```bash
sudo docker compose -f docker-compose.prod.yml exec api python -m app.seed_data
sudo docker compose -f docker-compose.prod.yml exec worker python seed_admin.py
```

> **Note:** the Postgres volume gets wiped by the troubleshooting steps
> above — if that ever happens again, re-run the seeding afterward, since
> it's gone along with everything else in the database.

---

## Part 3 — CI/CD via GitHub Actions

The workflow file lives at `.github/workflows/ci.yml`.

### 3.1 How it's structured

- **`on:`** triggers on push/PR to `main-v2`, plus `workflow_dispatch`
  (adds a manual "Run workflow" button in the Actions tab).
- **`test` job:** runs on every push automatically — installs deps, spins up
  throwaway Postgres/Redis service containers, runs migrations, runs
  `pytest`.
- **`deploy` job:** `needs: test` (won't run if tests fail), and gated by
  `if: github.event_name == 'workflow_dispatch'` — this is what makes it
  **continuous delivery, not continuous deployment**. A push only ever runs
  `test`; `deploy` shows as "skipped" unless the run was started by manually
  clicking "Run workflow".

> **Why not GitHub Environments + required reviewers**, which is the more
> "standard" way to gate a deploy job? That protection rule is a **paid
> feature for private repos** (free only for public repos). The
> `workflow_dispatch`-only gate achieves the same practical result — deploy
> only happens on a deliberate manual click — without needing any paid tier.

### 3.2 Secrets

Deploy needs 3 secrets, currently stored under an **Environment** named
`Server Deployment ANTS` (Settings → Environments) — **not** plain Repository
secrets. Because of that, the `deploy` job must declare
`environment: "Server Deployment ANTS"` to be able to read them at all; a
job that doesn't declare which environment it belongs to can't see
environment-scoped secrets.

| Secret | Value |
|---|---|
| `EC2_HOST` | `ants.thihaeung.com` |
| `EC2_USER` | `ubuntu` |
| `EC2_SSH_KEY` | private half of a **dedicated** deploy keypair (not your personal SSH key) |

To (re)generate that keypair, on the server:
```bash
ssh-keygen -t ed25519 -f ~/deploy_key -N ""
cat ~/deploy_key.pub >> ~/.ssh/authorized_keys
cat ~/deploy_key   # paste this whole output as the EC2_SSH_KEY secret
```

### 3.3 The server also needs its own way to pull from GitHub

Separate from the above (which lets GitHub Actions SSH *into* the server),
the server itself needs permission to `git pull` *from* GitHub — this repo
is private, and the original HTTPS clone can't authenticate non-interactively.

**Fix: a dedicated read-only Deploy Key, and switch the remote to SSH.**

On the server:
```bash
# 1. Generate a key just for GitHub access (different from deploy_key above)
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy_key -N ""
cat ~/.ssh/github_deploy_key.pub
```
Paste that public key into **GitHub → repo Settings → Deploy keys → Add
deploy key**. Leave "Allow write access" **unchecked** (read-only is enough
for pulling).

```bash
# 2. Tell SSH to use this specific key for github.com
cat > ~/.ssh/config << 'EOF'
Host github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/github_deploy_key
  IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config

# 3. Trust GitHub's host key (avoids an interactive "yes/no" prompt that
#    would otherwise block any non-interactive connection, like the
#    automated deploy job)
ssh-keyscan -H github.com >> ~/.ssh/known_hosts

# 4. Switch the repo's remote from HTTPS to SSH
cd ~/ants-backend
git remote set-url origin git@github.com:Morrowga/ant-core-system.git
git remote -v   # should now show git@github.com:..., not https://

# 5. Confirm it actually works
git pull origin main-v2
```

**Known gotcha:** at one point mid-setup, several files under
`~/ants-backend/.git/` ended up owned by `root` (from running
`sudo docker compose ...` commands), which caused
`error: cannot open '.git/FETCH_HEAD': Permission denied` for both manual
pulls and the automated deploy job (which connects as the regular `ubuntu`
user). Fix, if this recurs:
```bash
sudo chown -R $USER:$USER ~/ants-backend
```
Prefer running `docker compose` as your regular user (you're in the `docker`
group already) rather than with `sudo`, going forward, to avoid
reintroducing root-owned files into this folder.

### 3.4 How to actually trigger a deploy

1. Push code to `main-v2` → `test` runs automatically, `deploy` shows as
   skipped.
2. GitHub → **Actions tab → "Backend CI" → "Run workflow"** (branch:
   `main-v2`) → confirm.
3. This run has `deploy` actually execute: SSH into the server, `git pull
   origin main-v2`, `docker compose -f docker-compose.prod.yml up -d
   --build`.

**Note:** the "Run workflow" button only appears if the workflow file (with
`workflow_dispatch` in it) exists on the repo's **default branch** — this
repo's default branch was switched from `main` to `main-v2` for this reason,
since active work happens on `main-v2` and the button wouldn't show
otherwise.

---

## Part 4 — Frontends (Portal, HR Dashboard, Core Dashboard)

**Not yet done** — planned via Vercel's native Git integration (no code
changes needed, auto-deploys on push):

1. [vercel.com/new](https://vercel.com/new) → import each repo.
2. Build settings (Vite default): Build Command `yarn build`, Output
   Directory `dist`, Install Command `yarn install`.
3. Environment variables per project:
   - **Portal:** `VITE_API_BASE_URL=https://ants.thihaeung.com`
   - **HR Dashboard:** `VITE_API_BASE_URL=https://ants.thihaeung.com`,
     `VITE_CORE_DASHBOARD_URL=<core dashboard's Vercel URL>`
   - **Core Dashboard:** `VITE_API_BASE_URL=https://ants.thihaeung.com`,
     `VITE_HR_DASHBOARD_URL=<hr dashboard's Vercel URL>`,
     `VITE_STRIPE_PUBLISHABLE_KEY=<real value>`
4. Deploy each once to get real URLs, then go back and fill in the
   cross-referencing `VITE_*_URL` values above, then redeploy those two.

**After all three are live, back on the backend:**
```bash
nano ~/ants-backend/.env   # set FRONTEND_URL to Core Dashboard's real URL
cd ~/ants-backend
docker compose -f docker-compose.prod.yml up -d --build   # restart to apply
```
Also confirm CORS actually reads `FRONTEND_URL` (rather than a hardcoded
value elsewhere) so the real frontend origin is actually allowed.

---

## Quick Reference — Common Commands

```bash
# Check container status
sudo docker compose -f docker-compose.prod.yml ps

# Tail logs for one service
sudo docker compose -f docker-compose.prod.yml logs api --tail=50

# Restart everything (e.g. after an .env change)
sudo docker compose -f docker-compose.prod.yml up -d --build

# Check current DB migration state
sudo docker compose -f docker-compose.prod.yml run --rm api alembic current

# Re-seed demo data (only if you know the DB was reset)
sudo docker compose -f docker-compose.prod.yml exec api python -m app.seed_data
sudo docker compose -f docker-compose.prod.yml exec worker python seed_admin.py
```
