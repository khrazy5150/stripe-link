"""
Shared helper for loading the Junior Bay platform Cloudflare API token.

Primary source:
- AWS Secrets Manager secret referenced by CLOUDFLARE_API_TOKEN_SECRET_ARN

Fallback source:
- CLOUDFLARE_API_TOKEN environment variable
"""

import os
from typing import Optional

_CACHE: dict = {}


def _get_region() -> str:
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-west-2"


def get_cloudflare_api_token(*, refresh: bool = False) -> Optional[str]:
    if not refresh and "token" in _CACHE:
        return _CACHE["token"]

    arn = os.environ.get("CLOUDFLARE_API_TOKEN_SECRET_ARN")
    if arn:
        import boto3

        client = boto3.client("secretsmanager", region_name=_get_region())
        response = client.get_secret_value(SecretId=arn)
        token = (response.get("SecretString") or "").strip()
        if token:
            _CACHE["token"] = token
            return token

    env_token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if isinstance(env_token, str) and env_token.strip():
        _CACHE["token"] = env_token.strip()
        return _CACHE["token"]

    return None
