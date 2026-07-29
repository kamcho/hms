#!/usr/bin/env python
"""One-shot SHA UAT auth + eligibility test. Run: python scripts/test_sha_eligibility.py [id_number]"""
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

id_number = (sys.argv[1] if len(sys.argv) > 1 else "24241581").strip()
base = os.getenv("SHA_HIE_BASE_URL", "https://uat.dha.go.ke").rstrip("/")
user = os.getenv("SHA_HIE_USERNAME", "")
pwd = os.getenv("SHA_HIE_PASSWORD", "")
key = os.getenv("SHA_HIE_CONSUMER_KEY", "")

print("=== Step 1: Get JWT ===")
r1 = httpx.get(
    f"{base}/v1/hie-auth",
    params={"key": key},
    auth=(user, pwd),
    timeout=45,
)
print(f"Auth HTTP {r1.status_code}")
token = (r1.text or "").strip()
if r1.status_code != 200 or not token:
    print("Auth failed:", r1.text[:300])
    sys.exit(1)
print(f"JWT length: {len(token)}")
print()

print("=== Step 2: Eligibility ===")
params = {"identification_type": "National ID", "identification_number": id_number}
r2 = httpx.get(
    f"{base}/v2/eligibility",
    params=params,
    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    timeout=90,
)
print(f"Eligibility HTTP {r2.status_code}")
print("Body:", r2.text[:800])
print()

if sys.platform == "win32":
    from urllib.parse import urlencode

    qs = urlencode(params)
    print("=== PowerShell curl (token already embedded) ===")
    print(
        f'curl.exe -s "{base}/v2/eligibility?{qs}" '
        f'-H "Authorization: Bearer {token}" -H "Accept: application/json"'
    )
