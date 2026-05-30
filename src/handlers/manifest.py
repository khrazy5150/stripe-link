from stripe_link.common import json_response, runtime_manifest


def lambda_handler(event, context):
    return json_response(runtime_manifest())
