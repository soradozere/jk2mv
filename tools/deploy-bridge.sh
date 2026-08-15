#!/usr/bin/env bash
#
# Put ws-udp-bridge.py on the spectate box and restart it.
#
# Written down because it was not: the bridge was first deployed by hand over
# SSH during a session, and nothing in the repo recorded where it lived, what
# ran it, or how to put a new copy there. That is fine exactly once.
#
# The order here is deliberate. Back up before copying, byte-compile before
# restarting, and check the endpoint after -- so a syntax error is caught while
# the old bridge is still serving, rather than discovered by a viewer looking
# at a dead page.
set -euo pipefail

HOST="${BRIDGE_HOST:-soradozer@34.150.239.4}"
KEY="${BRIDGE_KEY:-$HOME/.ssh/gcp_livespectate}"
# The public name Caddy holds the certificate for. sslip.io encodes the IP in
# the hostname, so this tracks the VM's address -- if the box is ever rebuilt
# with a new IP, this changes with it.
PUBLIC_URL="${BRIDGE_URL:-https://34-150-239-4.sslip.io}"

REMOTE_PY=/home/soradozer/ws-udp-bridge.py
REMOTE_VENV=/home/soradozer/bridge-venv/bin/python3
SERVICE=jk2-bridge

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
local_py="$here/ws-udp-bridge.py"
[ -f "$local_py" ] || { echo "no ws-udp-bridge.py next to this script" >&2; exit 1; }

ssh_() { ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=10 "$HOST" "$@"; }

echo "==> viewers connected right now"
# Restarting drops everyone watching. Worth seeing the number before you do it
# rather than finding out from someone in Discord.
curl -s --max-time 5 "$PUBLIC_URL/status" || echo "(status endpoint not answering -- old bridge, or it is down)"
echo

stamp="$(date +%Y%m%d-%H%M%S)"
echo "==> backing up to $REMOTE_PY.bak-$stamp"
ssh_ "cp '$REMOTE_PY' '$REMOTE_PY.bak-$stamp'"

echo "==> copying"
scp -i "$KEY" -o BatchMode=yes "$local_py" "$HOST:$REMOTE_PY"

echo "==> byte-compiling before restart"
ssh_ "$REMOTE_VENV -m py_compile '$REMOTE_PY'"

echo "==> restarting $SERVICE"
ssh_ "sudo systemctl restart $SERVICE"
ssh_ "sleep 2; systemctl is-active $SERVICE"

echo "==> checking the endpoint came back"
if curl -sf --max-time 8 "$PUBLIC_URL/status"; then
	echo "==> deployed"
else
	echo "!! $PUBLIC_URL/status did not answer. Roll back with:" >&2
	echo "   ssh -i $KEY $HOST 'cp $REMOTE_PY.bak-$stamp $REMOTE_PY && sudo systemctl restart $SERVICE'" >&2
	exit 1
fi
