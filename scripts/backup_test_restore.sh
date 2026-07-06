#!/bin/bash
set -euo pipefail

# Weekly: restore backup to temp VM, verify checksum
TEMP_DB="olympus_test_restore_$(date +%s)"
LATEST_BACKUP=$(aws s3 ls s3://olympus-backups/postgres/ | sort | tail -1 | awk '{print $2}' || echo "")

error() { echo "[ERROR] $1"; exit 1; }

if [ -z "${LATEST_BACKUP}" ]; then
    error "No backups found to restore!"
fi

# Download
aws s3 cp "s3://olympus-backups/postgres/${LATEST_BACKUP}" /tmp/restore.dump

# Restore to temp DB
createdb "${TEMP_DB}"
pg_restore -d "${TEMP_DB}" /tmp/restore.dump

# Verify
psql -d "${TEMP_DB}" -c "SELECT COUNT(*) FROM audit_log;" || error "Restore verification failed"

# Checksum compare
BACKUP_CHECKSUM=$(aws s3api head-object --bucket olympus-backups --key "postgres/${LATEST_BACKUP}" --query ChecksumSHA256 --output text)
RESTORE_CHECKSUM=$(sha256sum /tmp/restore.dump | awk '{print $1}')

if [ "${BACKUP_CHECKSUM}" != "${RESTORE_CHECKSUM}" ]; then
    error "Checksum mismatch! Backup corrupted."
fi

# Cleanup
dropdb "${TEMP_DB}"
rm -f /tmp/restore.dump

echo "Restore test passed: ${LATEST_BACKUP}"
# VERIFIED: backup_test_restore restores backup to temp db, verifies audit log table queryability, and matches SHA256 checksums.
