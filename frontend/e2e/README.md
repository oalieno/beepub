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
./e2e/stack.sh up      # build from the working tree and start
./e2e/stack.sh down    # tear down, volumes included
```

`pnpm test:e2e` runs `stack.sh up` itself before the suite, so the stack
is always the current working tree — an unchanged tree is a near-instant
cache hit. The `up` images are baked builds: running Playwright directly
(`pnpm exec playwright test`, fine for spec iteration) tests whatever the
last build was, not your edits.

The script pins the compose project name to `beepub-e2e`; never run the
base compose file for testing without a `-p` — the default project name
would replace a live beepub stack running on the same daemon.

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
