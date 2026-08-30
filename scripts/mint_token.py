#!/usr/bin/env python3
"""Mint an access token for a deployment running with auth_mode=jwt.

The API verifies bearer tokens against JWT_SECRET, so whoever holds that secret can
sign one. This runs entirely offline - it never contacts the deployment - which is why
it works against a production API that exposes no token endpoint at all.

    JWT_SECRET=... python3 scripts/mint_token.py --role platform_admin

Paste the printed token into the sign-in box at /login.

The claims must match the deployment's own settings: --issuer and --audience default to
the API defaults, so override them if that deployment sets JWT_ISSUER or JWT_AUDIENCE.
A token is a credential for as long as it lives; keep --minutes short.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

try:
    import jwt
except ImportError:  # pragma: no cover - guidance, not logic
    sys.exit("PyJWT is not installed. Run: pip install pyjwt")

ROLES = ["platform_admin", "project_director", "project_engineer", "viewer"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--role", default="project_director", choices=ROLES)
    parser.add_argument("--user-id", default="pilot-admin")
    parser.add_argument("--tenant-id", default="demo-tenant")
    parser.add_argument("--organization-id", default="demo-org")
    parser.add_argument("--email", default=None)
    parser.add_argument("--minutes", type=int, default=60, help="lifetime in minutes (default 60)")
    parser.add_argument("--issuer", default=os.environ.get("JWT_ISSUER", "oneai-construction-twin"))
    parser.add_argument("--audience", default=os.environ.get("JWT_AUDIENCE", "construction-twin-api"))
    parser.add_argument("--algorithm", default=os.environ.get("JWT_ALGORITHM", "HS256"))
    args = parser.parse_args()

    secret = os.environ.get("JWT_SECRET")
    if not secret:
        sys.exit("Set JWT_SECRET to the deployment's signing secret.")

    now = datetime.now(timezone.utc)
    claims = {
        "sub": args.user_id,
        "tenant_id": args.tenant_id,
        "organization_id": args.organization_id,
        "role": args.role,
        "iss": args.issuer,
        "aud": args.audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=args.minutes)).timestamp()),
    }
    if args.email:
        claims["email"] = args.email

    print(jwt.encode(claims, secret, algorithm=args.algorithm))


if __name__ == "__main__":
    main()
