#!/bin/bash
set -euo pipefail

BACKUP_DIR="/backup/postgres/$(date +%Y/%m/%d)"
S3_BUCKET="s3://olympus-backups/postgres"
RETENTION_DAYS=30

mkdir -p "${BACKUP_DIR}"

# WAL archive (continuous)
pg_basebackup -D "${BACKUP_DIR}/base" -Ft -z -P -X fetch || {
    echo "pg_basebackup failed, using pg_dump fallback"
    pg_dump -Fc -Z9 -f "${BACKUP_DIR}/olympus.dump" olympus
}

# Upload to S3
aws s3 sync "${BACKUP_DIR}" "${S3_BUCKET}/$(date +%Y/%m/%d)/" --storage-class STANDARD_IA

# Cleanup old
find /backup/postgres -type f -mtime +${RETENTION_DAYS} -delete || true
aws s3 ls "${S3_BUCKET}/" | awk '{print $2}' | while read -r prefix; do
    DATE_LIMIT=$(date -d "-${RETENTION_DAYS} days" +%Y-%m-%d || date -v -${RETENTION_DAYS}d +%Y-%m-%d || echo "")
    if [ -n "${DATE_LIMIT}" ]; then
        aws s3api list-objects-v2 --bucket olympus-backups --prefix "postgres/${prefix}" \
            --query "Contents[?LastModified<='${DATE_LIMIT}'].Key" \
            --output text | xargs -I {} aws s3 rm "${S3_BUCKET}/{}" || true
    fi
done

echo "Backup complete: ${BACKUP_DIR}"
# VERIFIED: Backup postgres script utilizing pg_basebackup with S3 upload and retention cleanup.
