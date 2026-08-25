# v0.6 Summary

OneAI Construction Twin v0.6 upgrades infrastructure-scale IFC conversion from an in-process request into a distributed, durable and resumable asset pipeline.

Key additions:

- PostgreSQL/SQLite durable build jobs and partitions
- Redis wake-up channel
- horizontally scalable worker entrypoint
- source IFC object storage
- local/S3/MinIO output storage
- content-addressed cache and active-job de-duplication
- partition checkpoint, cancellation and resume
- job events, SSE and progress UI
- optional Meshopt/Draco adapter
- Docker worker scaling and Kubernetes worker/HPA scaffold

All v0.1–v0.5 APIs and product surfaces remain in the complete package.
