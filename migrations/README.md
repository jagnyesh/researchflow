# Database Migrations

This directory contains SQL migrations for the ResearchFlow database.

---

## Migration 001: Preview Extraction Fields

**Date**: 2025-11-04
**Status**: Ready to apply

### What It Does

Adds 4 new columns to the `data_deliveries` table to support the preview extraction workflow:

| Column | Type | Description |
|--------|------|-------------|
| `preview_data` | JSONB | Stores 10-row preview for each data element |
| `preview_qa_report` | JSONB | Stores auto-QA validation results |
| `delivery_approved_by` | VARCHAR | Informatician who approved delivery |
| `delivery_approved_at` | TIMESTAMP | When delivery was approved |

---

## How to Apply Migration

### Option 1: Using Python Script (Recommended)

```bash
# Apply migration
python migrations/apply_migration.py

# Rollback migration
python migrations/apply_migration.py --rollback
```

### Option 2: Using psql (Manual)

```bash
# Apply migration
PGPASSWORD=researchflow psql -h localhost -p 5434 -U researchflow -d researchflow \
  -f migrations/001_add_preview_fields_to_data_deliveries.sql

# Rollback migration
PGPASSWORD=researchflow psql -h localhost -p 5434 -U researchflow -d researchflow \
  -f migrations/001_rollback_preview_fields.sql
```

### Option 3: Using Database URL

```bash
# Apply migration with custom database URL
python migrations/apply_migration.py \
  --database-url postgresql+asyncpg://user:pass@localhost:5434/db

# Rollback with custom database URL
python migrations/apply_migration.py --rollback \
  --database-url postgresql+asyncpg://user:pass@localhost:5434/db
```

---

## Verification

After applying the migration, verify the columns exist:

```bash
PGPASSWORD=researchflow psql -h localhost -p 5434 -U researchflow -d researchflow \
  -c "\d data_deliveries"
```

Expected output:
```
                                           Table "public.data_deliveries"
        Column          |            Type             | Collation | Nullable |                  Default
------------------------+-----------------------------+-----------+----------+--------------------------------------------
 id                     | integer                     |           | not null | nextval('data_deliveries_id_seq'::regclass)
 ...
 preview_data           | jsonb                       |           |          |
 preview_qa_report      | jsonb                       |           |          |
 delivery_approved_by   | character varying           |           |          |
 delivery_approved_at   | timestamp without time zone |           |          |
```

---

## Rollback Strategy

If you need to rollback the migration:

1. **Back up data** (if preview columns contain important data):
   ```sql
   SELECT request_id, preview_data, preview_qa_report
   FROM data_deliveries
   WHERE preview_data IS NOT NULL OR preview_qa_report IS NOT NULL;
   ```

2. **Run rollback script**:
   ```bash
   python migrations/apply_migration.py --rollback
   ```

3. **Verify rollback**:
   ```bash
   PGPASSWORD=researchflow psql -h localhost -p 5434 -U researchflow -d researchflow \
     -c "\d data_deliveries" | grep -E "(preview|delivery_approved)"
   ```
   Should return no results.

---

## Safety Features

The migration scripts include safety checks:

✅ **Idempotent**: Can be run multiple times without errors
✅ **Non-destructive**: Uses `ADD COLUMN IF NOT EXISTS`
✅ **Verification**: Automatically verifies column count after migration
✅ **Rollback protection**: Requires explicit confirmation for rollback

---

## Migration History

| # | Date | Description | Status |
|---|------|-------------|--------|
| 001 | 2025-11-04 | Add preview extraction fields | ✅ Ready |

---

## Troubleshooting

### Error: "relation 'data_deliveries' does not exist"

The database tables haven't been created yet. Run:
```bash
python -c "
import asyncio
from app.database import init_db
asyncio.run(init_db())
"
```

### Error: "column already exists"

The migration has already been applied. This is safe to ignore.

### Error: "connection refused"

Check that PostgreSQL is running:
```bash
docker ps | grep postgres
```

If not running:
```bash
docker-compose -f config/docker-compose.yml up -d
```

---

## Future Migrations

To create a new migration:

1. Create SQL files:
   - `migrations/00X_description.sql` (forward migration)
   - `migrations/00X_rollback_description.sql` (rollback)

2. Update `apply_migration.py` to reference new migration files

3. Test migration on development database

4. Document in this README

---

## Development vs. Production

**Development** (localhost):
```bash
DATABASE_URL=postgresql+asyncpg://researchflow:researchflow@localhost:5434/researchflow
```

**Production** (AWS/cloud):
```bash
DATABASE_URL=postgresql+asyncpg://prod_user:prod_pass@prod_host:5432/prod_db
```

Always test migrations on development first!
