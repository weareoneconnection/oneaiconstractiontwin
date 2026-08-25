# Backup and Restore

## Create a backup

```bash
./scripts/backup.sh pilot-before-release
```

The backup contains:
- PostgreSQL custom-format dump or a consistent SQLite backup
- Object-store archive
- Manifest with SHA256 checksums and application metadata

## Verify

```bash
python apps/api/scripts/backup.py verify data/backups/<backup-directory>
```

## Restore

Stop API and workers, verify the target environment, then:

```bash
./scripts/restore.sh data/backups/<backup-directory> RESTORE
```

Restore is destructive. A literal `RESTORE` confirmation is required.

## Pilot release requirement
Before customer data is accepted:
1. Create a backup.
2. Verify checksums.
3. Restore into a clean test environment.
4. Confirm database records and one generated asset.
5. Record elapsed recovery time and data-loss window.

The default retention is 14 days and must be adapted to the customer contract.
