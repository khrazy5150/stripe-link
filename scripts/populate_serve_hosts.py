#!/usr/bin/env python3
"""Populate app_config serve-host values FROM THE DEPLOYED STACK (deploy-populated, never hand-typed).

Reads TestServeDomainName + PreviewLiveDomainName from the CloudFormation stack for {env} and writes
environments.{env}.{test_pages_host, pages_preview_base_url} into that env's app_config global doc — the shape the
dashboard's getTestPagesHost() / getPreviewPagesBaseUrl() read. Run after each `sam deploy` (plans/SERVE_HOST_SCHEME.md).

Usage: python3 scripts/populate_serve_hosts.py <dev|prod>
"""
import sys
import boto3

REGION = "us-west-2"


def main(env: str) -> None:
    cf = boto3.client("cloudformation", region_name=REGION)
    params = {
        p["ParameterKey"]: p["ParameterValue"]
        for p in cf.describe_stacks(StackName=f"jb-stripe-link-stack-{env}")["Stacks"][0].get("Parameters", [])
    }
    test_host = (params.get("TestServeDomainName") or "").strip()
    live_host = (params.get("PreviewLiveDomainName") or "").strip()
    if not test_host or not live_host:
        sys.exit(f"[{env}] stack is missing host params: TestServeDomainName={test_host!r} PreviewLiveDomainName={live_host!r}")

    table = boto3.resource("dynamodb", region_name=REGION).Table(f"jb-app-config-{env}")
    item = table.get_item(Key={"config_key": "app_config", "environment": "global"})["Item"]
    channel = item.setdefault("environments", {}).setdefault(env, {})
    channel["test_pages_host"] = test_host
    channel["pages_preview_base_url"] = f"https://{live_host}"
    table.put_item(Item=item)
    print(f"[{env}] environments.{env}.test_pages_host = {test_host}")
    print(f"[{env}] environments.{env}.pages_preview_base_url = https://{live_host}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("dev", "prod"):
        sys.exit("usage: populate_serve_hosts.py <dev|prod>")
    main(sys.argv[1])
