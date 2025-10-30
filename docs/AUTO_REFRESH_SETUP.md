# Auto-Refresh Setup for Materialized Views

This guide explains how to set up automated nightly refresh of materialized views using cron.

## Overview

The `scripts/refresh_materialized_views.py` script refreshes all materialized views in the `sqlonfhir` schema. This should be run nightly to keep the batch layer up-to-date with recent FHIR data.

## Prerequisites

- Python environment with dependencies installed
- Access to HAPI database (port 5433)
- ResearchFlow database (for metadata tracking)

## Manual Execution

Test the script manually first:

```bash
cd /Users/jagnyesh/Development/FHIR_PROJECT

# Set environment variables
export DATABASE_URL=sqlite+aiosqlite:///./dev.db
export HAPI_DB_URL=postgresql://hapi:hapi@localhost:5433/hapi

# Run refresh
python scripts/refresh_materialized_views.py
```

## Automated Setup (Cron)

### Option 1: User Crontab

Edit your crontab:

```bash
crontab -e
```

Add this entry (runs at 2 AM daily):

```cron
# Refresh materialized views nightly at 2 AM
0 2 * * * cd /Users/jagnyesh/Development/FHIR_PROJECT && \
  export DATABASE_URL=sqlite+aiosqlite:///./dev.db && \
  export HAPI_DB_URL=postgresql://hapi:hapi@localhost:5433/hapi && \
  /Users/jagnyesh/Development/FHIR_PROJECT/.venv/bin/python \
  /Users/jagnyesh/Development/FHIR_PROJECT/scripts/refresh_materialized_views.py \
  >> /Users/jagnyesh/Development/FHIR_PROJECT/logs/refresh_views.log 2>&1
```

### Option 2: System Crontab (Production)

For production deployments, use system crontab:

```bash
sudo vim /etc/cron.d/researchflow-refresh
```

Add:

```cron
# Refresh ResearchFlow materialized views nightly
0 2 * * * researchflow cd /opt/researchflow && \
  export DATABASE_URL=postgresql+asyncpg://researchflow:PASSWORD@localhost/researchflow && \
  export HAPI_DB_URL=postgresql://hapi:PASSWORD@localhost:5433/hapi && \
  /opt/researchflow/.venv/bin/python scripts/refresh_materialized_views.py \
  >> /var/log/researchflow/refresh_views.log 2>&1
```

### Option 3: Docker Deployment

For containerized deployments, use Docker Compose with a cron service:

Add to `docker-compose.yml`:

```yaml
services:
  # ... existing services ...

  refresh-cron:
    image: researchflow:latest
    command: >
      sh -c "echo '0 2 * * * cd /app && python scripts/refresh_materialized_views.py >> /var/log/refresh.log 2>&1' | crontab - && crond -f"
    environment:
      - DATABASE_URL=postgresql+asyncpg://researchflow:researchflow@db:5432/researchflow
      - HAPI_DB_URL=postgresql://hapi:hapi@hapi-db:5432/hapi
    depends_on:
      - db
      - hapi-db
    volumes:
      - refresh_logs:/var/log
    profiles:
      - production  # Only run in production
```

## Logs Directory

Create logs directory if it doesn't exist:

```bash
mkdir -p /Users/jagnyesh/Development/FHIR_PROJECT/logs
```

## Verify Cron Job

Check that cron job is registered:

```bash
crontab -l
```

Monitor logs:

```bash
tail -f /Users/jagnyesh/Development/FHIR_PROJECT/logs/refresh_views.log
```

## Cron Schedule Syntax

```
* * * * * command
│ │ │ │ │
│ │ │ │ └─── Day of week (0-7, Sunday=0 or 7)
│ │ │ └───── Month (1-12)
│ │ └─────── Day of month (1-31)
│ └───────── Hour (0-23)
└─────────── Minute (0-59)
```

Examples:
- `0 2 * * *` - Every day at 2:00 AM
- `0 */4 * * *` - Every 4 hours
- `30 1 * * 0` - Every Sunday at 1:30 AM

## Troubleshooting

### Cron not executing

1. Check cron is running:
   ```bash
   ps aux | grep cron
   ```

2. Check system logs:
   ```bash
   tail -f /var/log/system.log | grep cron
   ```

3. Verify PATH in cron:
   ```bash
   # Add to crontab
   PATH=/usr/local/bin:/usr/bin:/bin
   ```

### Database connection failures

- Ensure HAPI database is accessible
- Check firewall rules
- Verify credentials in environment variables

### Permission errors

- Ensure script is executable: `chmod +x scripts/refresh_materialized_views.py`
- Check logs directory permissions: `chmod 755 logs/`

## Integration with Speed Layer

The materialized views (batch layer) work together with Redis (speed layer):

1. **Nightly refresh** updates the batch layer with all data
2. **Redis cache** captures data added/updated since last refresh
3. **HybridRunner** merges both for complete results

This ensures queries always see:
- Bulk of data from fast materialized views
- Recent changes from Redis cache
- Near real-time accuracy with optimal performance

## Next Steps

After setting up auto-refresh:

1. Monitor first few runs to ensure success
2. Set up alerts for refresh failures
3. Consider refresh frequency based on data volume
4. Implement incremental refresh for very large views
