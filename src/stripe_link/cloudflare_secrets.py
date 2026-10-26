"""
Loading the Junior Bay platform Cloudflare API tokens. There are TWO, deliberately.

`get_cloudflare_api_token()` -- custom hostnames. Scoped to our own zones, used on every connect, every
Verify and every health sweep. Wide reach through the code, narrow power.

`get_cloudflare_dns_token()` -- managed DNS (plans/MANAGED_DNS.md). Can create zones on the account and
edit DNS on all of them, which means it can rewrite any tenant's records, mail included. Narrow reach
through the code, wide power.

KEEPING THEM APART IS THE POINT. Folding the second permission into the first would hand that power to
every code path that merely needs to check a certificate, and a leak of the busy credential would stop
being recoverable. Falls back to the custom-hostname token only when no DNS token is configured, so an
environment that has not set one up fails on Cloudflare's own permission error -- which names the missing
scope -- rather than on a confusing empty credential.

Each resolves from a Secrets Manager ARN in the environment, then from a plain environment variable.
"""

import os
from typing import Optional

_CACHE: dict = {}


def _get_region() -> str:
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-west-2"


def _token_from(arn_var: str, env_var: str, cache_key: str, refresh: bool) -> Optional[str]:
    if not refresh and cache_key in _CACHE:
        return _CACHE[cache_key]
    arn = os.environ.get(arn_var)
    if arn:
        import boto3

        client = boto3.client("secretsmanager", region_name=_get_region())
        response = client.get_secret_value(SecretId=arn)
        token = (response.get("SecretString") or "").strip()
        if token and not token.startswith("PLACEHOLDER"):
            _CACHE[cache_key] = token
            return token
    env_token = os.environ.get(env_var)
    if isinstance(env_token, str) and env_token.strip():
        _CACHE[cache_key] = env_token.strip()
        return _CACHE[cache_key]
    return None


def get_cloudflare_dns_token(*, refresh: bool = False) -> Optional[str]:
    """The managed-DNS token: creates zones, edits DNS on all of them.

    Falls back to the custom-hostname token when unset. That is not a shortcut -- it is what makes the
    failure legible. Without the fallback an unconfigured environment fails with an empty credential and
    a 400; with it, Cloudflare answers the real call and says exactly which permission is missing, which
    is the sentence someone needs in order to fix it.
    """
    return (_token_from("CLOUDFLARE_DNS_TOKEN_SECRET_ARN", "CLOUDFLARE_DNS_TOKEN", "dns", refresh)
            or get_cloudflare_api_token(refresh=refresh))


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
