from prometheus_client import Counter, Gauge, Histogram

ASSET_JOBS_CREATED = Counter("construction_twin_asset_jobs_created_total", "Distributed asset jobs created")
ASSET_JOBS_COMPLETED = Counter("construction_twin_asset_jobs_completed_total", "Distributed asset jobs completed")
ASSET_JOBS_FAILED = Counter("construction_twin_asset_jobs_failed_total", "Distributed asset jobs failed", ["phase"])
ASSET_CACHE_HITS = Counter("construction_twin_asset_cache_hits_total", "Content-addressed asset cache hits")
ASSET_PARTITIONS_COMPLETED = Counter("construction_twin_asset_partitions_completed_total", "Asset partitions completed")
ASSET_PARTITION_SECONDS = Histogram("construction_twin_asset_partition_seconds", "Asset partition processing time")
ASSET_OUTPUT_BYTES = Counter("construction_twin_asset_output_bytes_total", "Generated asset bytes")
ASSET_WORKER_LAST_CYCLE = Gauge("construction_twin_asset_worker_last_cycle_timestamp", "Unix timestamp of the latest worker cycle", ["worker_id"])
