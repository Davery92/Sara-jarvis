#!/usr/bin/env bash
# Sara iOS build 13 — harness rebuild Phase 7 (client_message_id + history merge).
# Per docs/plans/SARA_IOS_AND_WATCH_BUILD_UPDATE_RUNBOOK.md.
#
# Steps 1-3 (sync + deps + prebuild) run over SSH from here.
# Step 4 (the signed build) MUST run in a VISIBLE Mac Terminal: a background
# SSH-launched build compiles but fails signing with errSecInternalComponent
# because it cannot use the login keychain's private key.
set -euo pipefail
MAC=david@100.69.217.66
KEY=/home/david/.ssh/sara_agent
SSH="ssh -i $KEY -o IdentitiesOnly=yes"

echo "== 0. reachability =="
$SSH -o ConnectTimeout=10 $MAC 'echo ok' || {
  echo "Mac build host is offline — wake davids-macbook-air and re-run."; exit 1; }

echo "== 1. sync =="
cd /home/david/jarvis
rsync -az --delete \
  --exclude='.git/' --exclude='node_modules/' --exclude='ios/' \
  --exclude='.expo/' --exclude='DerivedData/' --exclude='build-sara-*.sh' \
  --exclude='*.log' \
  -e "$SSH" \
  ios-app/ $MAC:/Users/david/sara-ios-build/

echo "== 2. deps =="
$SSH $MAC 'cd /Users/david/sara-ios-build && npm install'

echo "== 3. prebuild =="
$SSH $MAC '
  export DEVELOPER_DIR=/Applications/Xcode-27-beta-4.app/Contents/Developer
  export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
  cd /Users/david/sara-ios-build && npx expo prebuild -p ios --clean'

cat <<'NEXT'

== 4. BUILD — run this in the VISIBLE Mac Terminal, not over SSH ==
    /Users/david/sara-ios-build/build-sara-watch-local.sh
Expect: ** BUILD SUCCEEDED ** / SARA_RELEASE_BUILD_SUCCEEDED
Then install to the iPhone per runbook section 7.
NEXT
