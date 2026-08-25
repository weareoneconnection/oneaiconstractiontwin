# Alpha v0.6 Architecture — Distributed Asset Pipeline

```text
                     API CONTROL PLANE
                             |
                 AssetBuildJob (durable DB)
                             |
              +--------------+--------------+
              |                             |
       Redis wake-up                  Job / Event API
              |                             |
              v                             v
       ASSET WORKER POOL              UI / SSE Monitor
              |
      +-------+-------+-------+
      |               |       |
  Partition 0     Partition 1 ... Partition N
      |               |       |
      +-------+-------+-------+
              |
     GLB LOD + optional compression
              |
      Content-addressed Object Prefix
              |
       S3 / MinIO / Local Storage
              |
       Cache Entry + Final Manifest
              |
          Cesium 3D Tiles
```

## Control-plane rules

- The database is the source of truth for jobs, partitions and leases.
- Redis is only a wake-up optimization; losing Redis does not lose work.
- A job is planned into durable partitions before conversion.
- Workers claim partitions with leases. Expired leases are recovered.
- Completed partitions are never rebuilt during normal resume.
- Finalization occurs only after every partition is completed.
- Identical completed builds reuse a content-addressed cache.
- Identical active requests are de-duplicated.

## Data-plane rules

- Source IFC is uploaded to object storage and can be materialized by any worker.
- Every GLB object is written atomically before partition completion.
- The final 3D Tiles tree references partition-relative content URIs.
- The manifest records source SHA, pipeline version, options, geometry modes, compression results and object keys.
- The Project World Model remains authoritative; generated assets are reproducible derivatives.

## Failure model

- Worker crash: lease expires and work returns to the queue.
- Partition failure: job becomes failed with completed checkpoints preserved.
- User cancellation: active work stops after the current safe unit; completed partitions remain.
- Resume: only incomplete partitions are returned to the queue.
- Optional compression failure: uncompressed GLB remains valid and the warning is recorded.
- Object storage or database outage: the partition remains uncommitted and can retry after recovery.
