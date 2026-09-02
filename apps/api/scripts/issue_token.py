"""Mint an access token for a deployment that authenticates with signed tokens.

With no identity provider configured, the sign-in page asks for a token rather than a
password, and this is what produces one. The token is signed with the deployment's own
`JWT_SECRET`, so it must be run with that secret in the environment — a token signed
with a different secret is rejected, which is the point.

    JWT_SECRET='…' python scripts/issue_token.py \
        --user maqing --tenant demo-tenant --organization demo-org --role platform_admin

Add `--verify https://api.example.com` to check the token against that deployment before
pasting it anywhere.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import argparse
import json
import urllib.error
import urllib.request

from app.core.config import settings
from app.core.security import ROLE_PERMISSIONS, issue_local_token


def main() -> int:
    parser = argparse.ArgumentParser(description="Issue a signed access token for the Construction Twin API")
    parser.add_argument("--user", default="operator", help="Becomes the token's subject and the audit actor id")
    parser.add_argument("--tenant", default="demo-tenant")
    parser.add_argument("--organization", default="demo-org")
    parser.add_argument("--role", default="platform_admin", choices=sorted(ROLE_PERMISSIONS))
    parser.add_argument("--email", default=None)
    parser.add_argument("--minutes", type=int, default=settings.jwt_exp_minutes, help="Lifetime in minutes")
    parser.add_argument("--verify", metavar="API_URL", help="Check the token against a deployment's /auth/me")
    parser.add_argument("--quiet", action="store_true", help="Print only the token, for piping")
    args = parser.parse_args()

    if settings.jwt_secret.startswith("development-only"):
        # Signing with the built-in default produces a token no real deployment accepts.
        print(
            "Refusing to sign with the built-in development secret.\n"
            "Set JWT_SECRET to the value the target deployment uses:\n"
            "  JWT_SECRET='<the deployment's secret>' python scripts/issue_token.py …",
            file=sys.stderr,
        )
        return 2

    token = issue_local_token(
        user_id=args.user,
        tenant_id=args.tenant,
        organization_id=args.organization,
        role=args.role,
        email=args.email,
        expires_minutes=args.minutes,
    )

    if args.verify:
        url = args.verify.rstrip("/") + "/api/v1/auth/me"
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                identity = json.loads(response.read())
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:300]
            print(f"The deployment rejected this token ({error.code}): {detail}", file=sys.stderr)
            print(
                "The usual cause is a JWT_SECRET that differs from the deployment's, "
                "or an issuer/audience mismatch.",
                file=sys.stderr,
            )
            return 1
        except urllib.error.URLError as error:
            print(f"Could not reach {url}: {error.reason}", file=sys.stderr)
            return 1
        if not args.quiet:
            print(
                f"Accepted by {args.verify}: {identity['user_id']} · {identity['role']} · "
                f"tenant {identity['tenant_id']} · {len(identity['permissions'])} permissions",
                file=sys.stderr,
            )

    if args.quiet:
        print(token)
        return 0

    print(f"\nRole      {args.role}")
    print(f"Scope     tenant {args.tenant} · organization {args.organization}")
    print(f"Valid for {args.minutes} minutes")
    print("\nPaste this into the sign-in page:\n")
    print(token)
    print("\nIt is a bearer credential: anyone holding it has this role until it expires.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
