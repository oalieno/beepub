#!/bin/sh
# Manage the disposable e2e stack. Wraps docker compose so the project
# name is always beepub-e2e — running the base compose file without an
# explicit project name would REPLACE a live beepub stack on the same
# docker daemon (plain `docker compose up` also auto-applies
# docker-compose.override.yml, which is the lab's config — never that).
#
#   ./e2e/stack.sh up        # build from the working tree and start
#   ./e2e/stack.sh dev       # dev mode: working-tree mounts + vite dev server
#                            # (frontend edits apply live, no image rebuild;
#                            # writes .svelte-kit-e2e so it can coexist with
#                            # the lab dev container on the same tree)
#   ./e2e/stack.sh down      # tear down, volumes included
#   ./e2e/stack.sh <any docker compose args>
#
# `up` and `dev` reconcile in place — switching modes recreates only the
# services whose definition changed. Run the e2e suite against `up` (the
# built image, what ships); use `dev` for probe/debug iteration.
set -eu

cd "$(dirname "$0")/../.."
export PORT="${E2E_PORT:-8091}"

DEV_FILES="-f docker-compose.yml -f docker-compose.dev.yml -f frontend/e2e/stack.dev.yml"

case "${1:-}" in
  up)
    shift
    exec docker compose -p beepub-e2e -f docker-compose.yml up -d --build "$@"
    ;;
  dev)
    shift
    # The image's root-owned /app/node_modules seeds the named volume on
    # first use, but the dev container runs as uid 1000 (so bind-mount
    # writes stay host-editable) and can't install into it. Fix ownership
    # once; the stat guard keeps later invocations instant.
    # shellcheck disable=SC2086
    docker compose -p beepub-e2e $DEV_FILES run --rm --no-deps -u root \
      --entrypoint sh frontend -c \
      '[ "$(stat -c %u /app/node_modules)" = "1000" ] || chown -R node:node /app/node_modules' \
      >/dev/null 2>&1 || true
    # shellcheck disable=SC2086
    exec docker compose -p beepub-e2e $DEV_FILES up -d "$@"
    ;;
  down)
    shift
    # Include the dev files so dev-only named volumes are removed too.
    # shellcheck disable=SC2086
    exec docker compose -p beepub-e2e $DEV_FILES down -v "$@"
    ;;
  *)
    exec docker compose -p beepub-e2e -f docker-compose.yml "$@"
    ;;
esac
