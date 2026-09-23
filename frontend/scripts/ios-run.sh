#!/usr/bin/env bash
# Build the web app, sync it into the iOS project, build it, and install +
# launch it on a connected iPhone — the same as pnpm build:app, npx cap sync,
# then Build & Run in Xcode.
#
#   pnpm ios:run                 # first paired device found
#   IOS_DEVICE=<name|udid> pnpm ios:run
#   IOS_TEAM=<team id> pnpm ios:run
#   IOS_SKIP_WEB=1 pnpm ios:run  # native-only change, skip the vite build
set -euo pipefail

cd "$(dirname "$0")/.."

# Use the full Xcode even when xcode-select points at the Command Line Tools.
if [[ -z "${DEVELOPER_DIR:-}" && -d /Applications/Xcode.app ]]; then
  export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
fi

TEAM="${IOS_TEAM:?set IOS_TEAM}"
DERIVED="ios/build"

if [[ -z "${IOS_SKIP_WEB:-}" ]]; then
  pnpm build:app
fi
npx cap sync ios

DEVICE="${IOS_DEVICE:-}"
if [[ -z "$DEVICE" ]]; then
  json="$(mktemp)"
  xcrun devicectl list devices --json-output "$json" >/dev/null 2>&1
  DEVICE="$(node -e '
    const d = JSON.parse(require("fs").readFileSync(process.argv[1], "utf8"));
    const dev = (d.result?.devices ?? []).find(
      (x) => x.hardwareProperties?.platform === "iOS" &&
             x.connectionProperties?.pairingState === "paired");
    if (dev) console.log(dev.identifier);
  ' "$json")"
  rm -f "$json"
  if [[ -z "$DEVICE" ]]; then
    echo "No paired iPhone found (xcrun devicectl list devices)." >&2
    exit 1
  fi
fi

xcodebuild \
  -project ios/App/App.xcodeproj \
  -scheme App \
  -configuration Debug \
  -destination "generic/platform=iOS" \
  -derivedDataPath "$DERIVED" \
  -allowProvisioningUpdates \
  DEVELOPMENT_TEAM="$TEAM" \
  -quiet \
  build

APP="$DERIVED/Build/Products/Debug-iphoneos/App.app"
xcrun devicectl device install app --device "$DEVICE" "$APP"
xcrun devicectl device process launch --device "$DEVICE" --terminate-existing com.beepub.app \
  || echo "Installed, but could not launch it — is the iPhone locked? Open BeePub by hand." >&2
