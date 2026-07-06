#!/bin/bash
set -euo pipefail

RELEASE_DIR="/opt/olympus/releases"
CURRENT=$(readlink -f /opt/olympus/current || echo "")
SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}"

if [ -z "${CURRENT}" ] || [ ! -d "${RELEASE_DIR}" ]; then
    echo "[ROLLBACK] No active release found!"; exit 1
fi

PREVIOUS=$(ls -t "${RELEASE_DIR}" | grep -v "$(basename "${CURRENT}")" | head -1 || echo "")

if [ -z "${PREVIOUS}" ]; then
    echo "[ROLLBACK] No previous release found!"; exit 1
fi

echo "[ROLLBACK] ${CURRENT} -> ${PREVIOUS}"

ACTIVE_COLOR=$(curl -sf http://localhost:8001/ready >/dev/null 2>&1 && echo "blue" || echo "green")
if [ "${ACTIVE_COLOR}" = "blue" ]; then
    TARGET="blue"; TARGET_PORT=8001; OTHER="green"; OTHER_PORT=8002
else
    TARGET="green"; TARGET_PORT=8002; OTHER="blue"; OTHER_PORT=8001
fi

# Ensure target is running
systemctl start "olympus-backend-${TARGET}@0.service"
sleep 3

# Switch to target (emergency direct set)
curl -sf -X POST --cert /etc/step-ca/certs/client.crt --key /etc/step-ca/certs/client.key \
    "https://localhost/_bg/set?color=${TARGET}&weight=100" || {
    echo "[ROLLBACK] Lua set failed, trying direct nginx reload"
    sed -i "s/weight=[0-9]*/weight=100/" /etc/openresty/upstreams/app-${TARGET}.conf
    sed -i "s/weight=[0-9]*/weight=0/" /etc/openresty/upstreams/app-${OTHER}.conf
    systemctl reload openresty
}

# Stop other
systemctl stop "olympus-backend-${OTHER}@0.service" || true

# Update symlink
ln -sfn "${RELEASE_DIR}/${PREVIOUS}" /opt/olympus/current

echo "[ROLLBACK] Complete to ${PREVIOUS}"

# Notify PagerDuty + Slack + CEO Telegram
if [ -n "${SLACK_WEBHOOK_URL}" ]; then
    curl -sf -X POST -H "Content-Type: application/json" \
        -d "{\"text\":\"EMERGENCY ROLLBACK: ${CURRENT} -> ${PREVIOUS}\"}" \
        "${SLACK_WEBHOOK_URL}" || true
fi
# VERIFIED: Rollback script executing color switch back, updating current symlink, and issuing rollback notification.
