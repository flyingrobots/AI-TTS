#!/bin/sh
# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0
#
# Replace the running AI-TTS launch agent with the one in a plist.
#
# Usage: restart-launch-agent.sh <service-target> <domain-target> <plist>
#   e.g. restart-launch-agent.sh gui/501/com.flyingrobots.ai-tts gui/501 \
#            ~/Library/LaunchAgents/com.flyingrobots.ai-tts.plist

set -eu

if [ "$#" -ne 3 ]; then
    printf 'usage: %s <service-target> <domain-target> <plist>\n' "$0" >&2
    exit 64
fi

SERVICE=$1
DOMAIN=$2
PLIST=$3

# bootout returns before launchd has finished removing the service, and a
# bootstrap in that window fails with error 5. Wait for the label to leave,
# polling every tenth of a second, for ten seconds by default.
POLLS=${AITTS_LAUNCHD_TEARDOWN_POLLS:-100}

launchctl bootout "$SERVICE" 2>/dev/null || true
polled=0
while launchctl print "$SERVICE" >/dev/null 2>&1; do
    polled=$((polled + 1))
    if [ "$polled" -ge "$POLLS" ]; then
        printf 'launchd is still tearing down %s; re-run once it has gone\n' "$SERVICE" >&2
        exit 1
    fi
    sleep 0.1
done
launchctl bootstrap "$DOMAIN" "$PLIST"
