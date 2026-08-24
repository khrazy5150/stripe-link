#!/usr/bin/env python3
"""Populate app_config serve-host values FROM THE DEPLOYED STACK (deploy-populated, never hand-typed).

Reads the CloudFormation stack for {env} and writes environments.{env}.{test_pages_host, pages_preview_base_url,
pages_base_url} into that env's app_config global doc — the shape the dashboard's getTestPagesHost() /
getPreviewPagesBaseUrl() / getPagesBaseUrl() read. Run after each `sam deploy` (plans/SERVE_HOST_SCHEME.md).

Usage: python3 scripts/populate_serve_hosts.py <dev|prod>
"""
import sys
import boto3

REGION = "us-west-2"


def main(env: str) -> None:
    cf = boto3.client("cloudformation", region_name=REGION)
    stack = cf.describe_stacks(StackName=f"jb-stripe-link-stack-{env}")["Stacks"][0]
    params = {p["ParameterKey"]: p["ParameterValue"] for p in stack.get("Parameters", [])}
    outputs = {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}
    test_host = (params.get("TestServeDomainName") or "").strip()
    live_host = (params.get("PreviewLiveDomainName") or "").strip()
    pages_domain = (outputs.get("PagesDistributionDomainName") or "").strip()
    if not test_host or not live_host or not pages_domain:
        sys.exit(f"[{env}] stack missing a value: TestServeDomainName={test_host!r} PreviewLiveDomainName={live_host!r} PagesDistributionDomainName={pages_domain!r}")

    table = boto3.resource("dynamodb", region_name=REGION).Table(f"jb-app-config-{env}")
    item = table.get_item(Key={"config_key": "app_config", "environment": "global"})["Item"]
    channel = item.setdefault("environments", {}).setdefault(env, {})
    channel["test_pages_host"] = test_host
    channel["pages_preview_base_url"] = f"https://{live_host}"
    channel["pages_base_url"] = f"https://{pages_domain}"
    table.put_item(Item=item)
    print(f"[{env}] environments.{env}.test_pages_host = {test_host}")
    print(f"[{env}] environments.{env}.pages_preview_base_url = https://{live_host}")
    print(f"[{env}] environments.{env}.pages_base_url = https://{pages_domain}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("dev", "prod"):
        sys.exit("usage: populate_serve_hosts.py <dev|prod>")
    main(sys.argv[1])
