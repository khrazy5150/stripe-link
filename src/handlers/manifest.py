from stripe_link.common import json_response
from stripe_link.runtime_manifest import runtime_manifest


def lambda_handler(event, context):
    return json_response(runtime_manifest())
