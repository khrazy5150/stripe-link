"""Shippo's `track_updated` webhook: the writer `tracking_status` never had.

`domain/tracking.py` explains why this exists. This half is the transport, and it does four things:
authenticate the caller, find the shipment by OUR id, hand the reading to the domain, and write only the
attributes the domain returned.

**It never trusts the body for anything but a status.** The shipment is located by `metadata`, a string we
put there ourselves when registering the tracker, so the payload cannot name a tenant, an order or an
amount. The worst a forged request can do is set a carrier status on a shipment whose id it already knew --
and `tracking.accepts` will not let it un-deliver one.

**Authentication FAILS CLOSED, which is the opposite of the Debounce key.** Shippo's HMAC option needs
their solutions team to provision a shared secret (up to ten business days), so the available mechanism
today is their echoed URL token: `?token=...`, compared against Secrets Manager. A missing secret rejects
everything rather than waving it through -- an unconfigured deploy must not accept anonymous writes to
delivery state, and an endpoint that silently stopped checking is worse than one that is plainly off.

**Always 200 once authenticated.** Shippo retries on 408, 429 and 5xx, so "I do not recognise this
shipment" has to read as success or a deleted test parcel generates retries for days.
"""
import json
import os
import time

from stripe_link.common import error_response, json_response, query_params
from stripe_link.domain.tracking import fields_to_write, reading, shipment_id_from
from stripe_link.repositories.documents import shipments_repository

# THE MODE IS CARRIED, NEVER INFERRED. Each deployment serves BOTH Stripe modes -- that is the whole point
# of the decoupling -- so the Shippo environment an event came from does not identify a deployment, and a
# deployment does not identify a mode. Shippo has no idea which of ours a parcel belongs to either, so the
# mode travels in the webhook URL we hand it: `?mode=live`, one webhook per (Shippo environment,
# deployment).
#
# Without it this handler searched the test partition and then the live one, which works right up until a
# shipment id exists in both -- and then a test-mode carrier event applies to a LIVE shipment. That is the
# mode bleed this repo has already paid for twice (`feedback_mode_not_environment`, and the shipping keys'
# own schema records a tenant in test mode buying real labels).
#
# Absent, both are still tried: a webhook registered before this existed must keep working, and trying is
# the old behaviour rather than a new guess. A DECLARED mode is never widened.
MODES = ("test", "live")

_TOKEN_CACHE: dict[str, str] = {}


def _region() -> str:
    return os.environ.get("AWS_REGION", "us-west-2")


def load_token(*, client=None) -> str:
    """The shared URL token, from Secrets Manager. "" means tracking ingestion is OFF.

    Not an environment variable, for `email_validation.load_api_key`'s reason: a secret in the template is
    a secret in git and in every deploy log. Cached per process.
    """
    secret_name = os.environ.get("SHIPPO_WEBHOOK_SECRET_NAME", "")
    if not secret_name:
        return ""
    if secret_name in _TOKEN_CACHE:
        return _TOKEN_CACHE[secret_name]
    if client is None:
        import boto3

        client = boto3.client("secretsmanager", region_name=_region())
    try:
        response = client.get_secret_value(SecretId=secret_name)
        data = json.loads(response.get("SecretString") or "{}")
        token = str((data or {}).get("token") or "").strip()
    except Exception:  # noqa: BLE001 - a denied secret leaves the endpoint closed, never open
        token = ""
    if token:
        _TOKEN_CACHE[secret_name] = token
    return token


def _authentic(event, token: str) -> bool:
    """Constant-time comparison of the echoed token. False when either side is empty."""
    import hmac

    supplied = str(query_params(event).get("token") or "").strip()
    if not supplied or not token:
        return False
    return hmac.compare_digest(supplied, token)


def _modes_for(event) -> tuple[str, ...]:
    """The partition(s) to search: the one the URL declares, or both when it declares none."""
    declared = str(query_params(event).get("mode") or "").strip().lower()
    return (declared,) if declared in MODES else MODES


def _find_shipment(shipment_id: str, *, repo_fn=shipments_repository, modes=MODES):
    """`(shipment, repo)` for the first mode that holds it, or `(None, None)`.

    `find_by_id` is a GSI1 query, so this is cross-tenant on purpose: the carrier does not know our
    tenants, and the document it finds carries the `tenant_id` the write needs.
    """
    failures = []
    for mode in modes:
        try:
            repo = repo_fn(mode=mode)
            found = repo.find_by_id(shipment_id)
        except Exception as exc:  # noqa: BLE001 - try the other mode, then give up
            failures.append(f"{mode}: {type(exc).__name__}: {exc}")
            continue
        if found:
            return found, repo
    if len(failures) == len(modes):
        # BOTH lookups ERRORED, which is not the same as neither finding anything -- an unset table name
        # or a denied query would otherwise read as "we do not know this parcel" and every delivery would
        # be dropped in silence, looking exactly like ordinary traffic (`feedback_one_guess_hides_the_cause`).
        print(f"[tracking] lookup failed in every mode for {shipment_id}: {'; '.join(failures)}")
    return None, None


def handler(event, context, repo_fn=shipments_repository, secrets_client=None,
            now_fn=lambda: int(time.time())):
    method = (event or {}).get("httpMethod", "").upper()
    if method == "OPTIONS":
        return json_response({})
    if method != "POST":
        return error_response(f"Unsupported method '{method}'.", status_code=405,
                              code="method_not_allowed")

    token = load_token(client=secrets_client)
    if not _authentic(event, token):
        # 401 and nothing else. Not "which half was wrong", not whether the secret is even configured:
        # the one thing this endpoint must not do is help someone guess their way in.
        return error_response("Unauthorized.", status_code=401, code="unauthorized")

    try:
        payload = json.loads((event or {}).get("body") or "{}")
    except (TypeError, ValueError):
        # A body we cannot parse will not parse on a retry either, so this is a 400 rather than a 5xx.
        return error_response("Body is not JSON.", code="invalid_payload")

    shipment_id = shipment_id_from(payload)
    update = reading(payload)
    if not shipment_id or not update:
        # Shippo sends events for trackers we did not register (a tenant tracking a parcel in their own
        # Shippo account) and statuses we do not model. Both are ordinary, and both are nothing to do.
        return json_response({"applied": False, "reason": "nothing_to_apply"})

    shipment, repo = _find_shipment(shipment_id, repo_fn=repo_fn, modes=_modes_for(event))
    if not shipment or repo is None:
        return json_response({"applied": False, "reason": "unknown_shipment"})

    fields = fields_to_write(shipment, update, now=int(now_fn()))
    if not fields:
        # A retry of an event we already hold, or one that would have moved a delivered parcel backwards.
        return json_response({"applied": False, "reason": "not_newer",
                              "tracking_status": shipment.get("tracking_status") or ""})

    try:
        applied = repo.update_tracking(str(shipment.get("tenant_id") or ""), shipment_id, fields)
    except Exception as exc:  # noqa: BLE001
        # A 5xx so Shippo retries: unlike a bad body, a failed write is worth attempting again, and
        # swallowing it would lose the delivery silently -- which is the one thing a delivery guarantee
        # cannot afford (`feedback_one_guess_hides_the_cause`, so the error is logged rather than guessed).
        print(f"[tracking] write failed for {shipment_id}: {type(exc).__name__}: {exc}")
        return error_response("Could not record tracking.", status_code=503, code="write_failed")

    return json_response({"applied": bool(applied),
                          "tracking_status": fields.get("tracking_status") or "",
                          "delivered_at": fields.get("delivered_at") or 0})
