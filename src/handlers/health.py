from datetime import datetime, timezone

from stripe_link.common import json_response, runtime_environment


def lambda_handler(event, context):
    return json_response({
        "ok": True,
        "service": "stripe-link",
        "environment": runtime_environment(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
