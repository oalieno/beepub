#!/usr/bin/env bash
# Build the iOS app and upload it to TestFlight — the same as pnpm build:app,
# npx cap sync, then Product > Archive > Distribute App in Xcode.
#
# Needs an App Store Connect API key (Users and Access > Integrations):
#   ASC_KEY_ID      the key's ID
#   ASC_ISSUER_ID   the issuer ID shown above the key list
#   ASC_KEY_PATH    the .p8 file (default ~/.appstoreconnect/private_keys/AuthKey_<ASC_KEY_ID>.p8)
# These can also live in ~/.appstoreconnect/beepub.env.
#
#   IOS_TEAM=<team id>          signing team
#   IOS_BUILD_NUMBER=<n.n>      CFBundleVersion (default: UTC timestamp, always increasing)
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -f ~/.appstoreconnect/beepub.env ]]; then
  # shellcheck disable=SC1090
  source ~/.appstoreconnect/beepub.env
fi

# Use the full Xcode even when xcode-select points at the Command Line Tools.
if [[ -z "${DEVELOPER_DIR:-}" && -d /Applications/Xcode.app ]]; then
  export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
fi

: "${ASC_KEY_ID:?set ASC_KEY_ID}"
: "${ASC_ISSUER_ID:?set ASC_ISSUER_ID}"
ASC_KEY_PATH="${ASC_KEY_PATH:-$HOME/.appstoreconnect/private_keys/AuthKey_${ASC_KEY_ID}.p8}"
[[ -f "$ASC_KEY_PATH" ]] || { echo "API key not found: $ASC_KEY_PATH" >&2; exit 1; }

TEAM="${IOS_TEAM:?set IOS_TEAM}"
BUILD_NUMBER="${IOS_BUILD_NUMBER:-$(date -u +%Y%m%d.%H%M%S)}"
OUT="ios/build/testflight"
ARCHIVE="$OUT/App.xcarchive"
AUTH=(
  -allowProvisioningUpdates
  -authenticationKeyPath "$ASC_KEY_PATH"
  -authenticationKeyID "$ASC_KEY_ID"
  -authenticationKeyIssuerID "$ASC_ISSUER_ID"
)

rm -rf "$OUT"
mkdir -p "$OUT"

pnpm build:app
npx cap sync ios

echo "Archiving build $BUILD_NUMBER"
xcodebuild \
  -project ios/App/App.xcodeproj \
  -scheme App \
  -configuration Release \
  -destination "generic/platform=iOS" \
  -derivedDataPath ios/build \
  -archivePath "$ARCHIVE" \
  "${AUTH[@]}" \
  DEVELOPMENT_TEAM="$TEAM" \
  CURRENT_PROJECT_VERSION="$BUILD_NUMBER" \
  -quiet \
  archive

cat >"$OUT/ExportOptions.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>method</key><string>app-store-connect</string>
  <key>destination</key><string>upload</string>
  <key>teamID</key><string>$TEAM</string>
  <key>signingStyle</key><string>automatic</string>
  <key>manageAppVersionAndBuildNumber</key><false/>
  <key>uploadSymbols</key><true/>
</dict>
</plist>
EOF

echo "Uploading to App Store Connect"
xcodebuild \
  -exportArchive \
  -archivePath "$ARCHIVE" \
  -exportOptionsPlist "$OUT/ExportOptions.plist" \
  -exportPath "$OUT/export" \
  "${AUTH[@]}"

echo "Uploaded build $BUILD_NUMBER; it shows up in TestFlight once Apple finishes processing."
