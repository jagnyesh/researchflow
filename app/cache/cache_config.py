"""Cache configuration and policies."""
from dataclasses import dataclass


@dataclass
class CacheConfig:
    """Redis cache configuration."""

    # TTL (time-to-live) in hours
    default_ttl_hours: int = 24
    patient_ttl_hours: int = 24
    condition_ttl_hours: int = 24
    observation_ttl_hours: int = 12  # Observations change more frequently

    # Scan limits
    scan_batch_size: int = 100
    max_scan_results: int = 10000

    # Connection settings
    connection_timeout_seconds: int = 5
    max_connections: int = 50

    # Refresh settings
    refresh_interval_minutes: int = 5  # How often to poll FHIR for changes


# Global config instance
cache_config = CacheConfig()
