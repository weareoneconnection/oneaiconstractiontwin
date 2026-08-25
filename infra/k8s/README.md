# Kubernetes Pilot Reference

1. Provision approved PostgreSQL, Redis and S3/MinIO services.
2. Edit and apply ConfigMap and Secret examples.
3. Apply the ServiceAccount.
4. Run the migration Job and wait for completion.
5. Deploy API, Asset Worker and Web.
6. Apply PDB, NetworkPolicies and the environment-specific Ingress.
7. Verify `/health/ready`, worker heartbeat, object storage, migrations and OIDC login.

These manifests are pilot references. Image registry, storage classes, ingress controller, certificates, egress policy and secret management must be aligned with the customer platform.
