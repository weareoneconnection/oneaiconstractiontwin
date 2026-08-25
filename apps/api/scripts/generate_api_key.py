import hashlib
import json
import secrets

key = "oct_" + secrets.token_urlsafe(32)
print("API key (show once):", key)
print("SHA-256 digest:", hashlib.sha256(key.encode()).hexdigest())
print("Example API_KEY_RECORDS_JSON entry:")
print(json.dumps({hashlib.sha256(key.encode()).hexdigest(): {
    "tenant_id": "replace-tenant",
    "organization_id": "replace-org",
    "user_id": "service-client",
    "role": "project_manager"
}}, indent=2))
