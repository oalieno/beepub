# Frontend e2e tests (Playwright)

The tests drive a real browser against a **full BeePub stack** (nginx →
frontend + backend + Postgres + Redis) reachable at `BASE_URL`. They assume
a disposable instance: the global setup registers the admin account on a
fresh stack and creates a library, all idempotently — re-runs against the
same stack are fine.

**Never point `BASE_URL` at an instance whose data you care about** — the
tests create users and books.

## Start a disposable stack

```sh
# From the repo root. -p is REQUIRED: without it the project is named
# "beepub" and would replace a live stack running on the same daemon.
PORT=8091 docker compose -p beepub-e2e -f docker-compose.yml up -d --build

# tear down (volumes included)
docker compose -p beepub-e2e -f docker-compose.yml down -v
```

## Run the tests

```sh
cd frontend
pnpm install
pnpm exec playwright install chromium   # first time only

# CI / local daemon:
pnpm test:e2e

# remote docker daemon (stack ports live on that host):
BASE_URL=http://<docker-host>:8091 pnpm test:e2e
```

`BASE_URL` defaults to `http://localhost:8091`. On plain-http non-localhost
targets the config auto-adds a Chromium flag so the Secure auth cookies
still work.
