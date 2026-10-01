"""Talking to a shipping provider. One interface, so a second provider is additive.

Standard library only: `src/requirements.txt` is deliberately empty, and Stripe is already called with
`urllib` in handlers/checkout.py. The legacy implementation in ../stripe-cart is built on `requests` in a
Lambda layer and cannot be copied for that reason -- its CALL SHAPES are the reference, not its code.

Money arrives from these APIs as a decimal STRING ("8.12"). It is converted through Decimal, never float:
`int(float("8.12") * 100)` is 811 on some values, and a rate that is one cent wrong is a price that is one
cent wrong on every order that uses it.
"""
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json

TIMEOUT_SECONDS = 20


class ProviderError(RuntimeError):
    """A provider refused, or could not be reached. Carries a message safe to show a tenant."""


def to_cents(amount: Any, currency: str = "usd") -> int:
    """A provider's decimal string to the smallest currency unit.

    Through Decimal on purpose. Binary floats cannot hold 8.12 exactly, so float arithmetic turns some
    perfectly ordinary rates into an off-by-one-cent -- and this number goes on to set prices.
    """
    try:
        value = Decimal(str(amount or "0"))
    except (InvalidOperation, ValueError):
        raise ProviderError(f"Could not read the rate amount '{amount}'.") from None
    # Zero-decimal currencies (JPY, KRW) are already in their smallest unit.
    if str(currency or "usd").lower() in {"jpy", "krw", "vnd", "clp"}:
        return int(value)
    return int((value * 100).quantize(Decimal("1")))


# Every adapter returns rates in ONE shape, because three callers read them and they must not each learn a
# provider's dialect: buying a label for an order (P2), estimating shipping at pricing time (PE), and the
# standalone carrier calculator (PC). `estimated_days` is part of that shape because "cheapest" is the wrong
# answer for a seller who promised two-day delivery -- the comparison needs both axes.
RATE_FIELDS = ("provider", "rate_id", "carrier", "service", "service_token",
               "amount", "currency", "estimated_days", "attributes")


class ShippingProvider:
    """What every adapter implements. Adding a provider means adding one of these, nothing else."""

    name = ""

    def test_connection(self) -> dict[str, Any]:
        """Prove the key works. Returns {"ok": bool, "message": str, "carriers": [...]}."""
        raise NotImplementedError

    def rates(self, *, from_address: dict, to_address: dict, parcel: dict) -> list[dict[str, Any]]:
        raise NotImplementedError

    def parcel_templates(self) -> list[dict[str, Any]]:
        """Carrier-supplied packaging -- USPS Flat Rate boxes, FedEx Paks and the like.

        The one case where a container's price really is destination-independent, because the CARRIER says
        so. A tenant's own carton is never that, whatever its dimensions: it is rated on size, weight and
        distance like anything else (plans/LIVE_SHIPPING_RATES.md phase 7).

        Empty by default rather than NotImplementedError: a provider with no template list is a provider
        offering no carrier packaging, which is a true answer and not a crash.
        """
        return []

    def buy_label(self, *, rate_id: str, label_format: str = "PDF",
                  idempotency_key: str = "") -> dict[str, Any]:
        """Turn a rate into a bought label. Returns the normalised purchase."""
        raise NotImplementedError

    def carrier_accounts(self) -> list[dict[str, Any]]:
        """The tenant's carrier accounts, with the ids a pickup or a manifest has to name."""
        raise NotImplementedError

    def validate_address(self, address: dict) -> dict[str, Any]:
        """Is this a real, deliverable address? Returns {valid, messages, normalized}.

        `valid` is True, False, or **None for "the provider would not say"** -- which is not the same as
        False, and must never be shown to a tenant as an undeliverable address.
        """
        raise NotImplementedError

    def schedule_pickup(self, *, carrier_account: str, location: dict, transactions: list[str],
                        start_time: str, end_time: str) -> dict[str, Any]:
        """Ask the carrier to collect. Returns {confirmation, window, status}."""
        raise NotImplementedError

    def create_manifest(self, *, carrier_account: str, ship_date: str, address_from: str,
                        transactions: list[str]) -> dict[str, Any]:
        """The end-of-day handover document (USPS calls it a SCAN form)."""
        raise NotImplementedError


class ShippoProvider(ShippingProvider):
    """Shippo over its REST API. Test mode is carried by the KEY -- a test token returns test rates and
    buys free test labels on the same host -- so there is no sandbox URL to switch to."""

    name = "shippo"
    BASE_URL = "https://api.goshippo.com"

    def __init__(self, api_key: str, *, base_url: str = "", opener=None):
        if not str(api_key or "").strip():
            raise ProviderError("A Shippo API key is required.")
        self._api_key = str(api_key).strip()
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self._opener = opener or urlopen

    def _request(self, path: str, *, payload: dict | None = None, params: dict | None = None,
                 idempotency_key: str = "") -> Any:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        headers = {
            "Authorization": f"ShippoToken {self._api_key}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Shippo-Idempotency-Key"] = idempotency_key
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers=headers,
            method="POST" if payload is not None else "GET",
        )
        try:
            with self._opener(request, timeout=TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            # Read the body: the provider explains itself there, and "HTTP Error 401" explains nothing.
            # NEVER include the request in the message -- its headers carry the key.
            detail = ""
            try:
                body = json.loads(exc.read().decode("utf-8"))
                detail = str(body.get("detail") or body.get("message") or body)[:300]
            except Exception:  # noqa: BLE001 - an unparseable body must not replace the status
                detail = ""
            if exc.code in (401, 403):
                raise ProviderError("Shippo rejected the API key.") from None
            raise ProviderError(f"Shippo returned {exc.code}. {detail}".strip()) from None
        except URLError as exc:
            raise ProviderError(f"Could not reach Shippo: {exc.reason}") from None
        except json.JSONDecodeError:
            raise ProviderError("Shippo returned a response that could not be read.") from None

    def test_connection(self) -> dict[str, Any]:
        """Lists carrier accounts: it proves the key AND reports which carriers this account can quote,
        which is what the carrier calculator needs before it can offer a comparison."""
        body = self._request("/carrier_accounts", params={"results": 10})
        carriers = sorted({
            str(entry.get("carrier") or "").strip()
            for entry in (body.get("results") or [])
            if entry.get("active") and entry.get("carrier")
        })
        return {"ok": True, "message": "Connected to Shippo.", "carriers": carriers}

    def rates(self, *, from_address: dict, to_address: dict, parcel: dict) -> list[dict[str, Any]]:
        body = self._request("/shipments", payload={
            "address_from": _shippo_address(from_address),
            "address_to": _shippo_address(to_address),
            "parcels": [_shippo_parcel(parcel)],
            "async": False,
        })
        messages = body.get("messages") or []
        rates = body.get("rates") or []
        if not rates:
            detail = "; ".join(str(m.get("text") or "") for m in messages if m.get("text"))[:300]
            raise ProviderError(detail or "Shippo returned no rates for that parcel and address.")
        return [_shippo_rate(rate) for rate in rates]

    def parcel_templates(self) -> list[dict[str, Any]]:
        # GET /parcel-templates/ -- "a package used for shipping that has preset dimensions defined by a
        # carrier" (Shippo). The `token` is what `_shippo_parcel` already forwards as `template`, so
        # adopting one needs no change to the rating path at all.
        body = self._request("/parcel-templates", params={"results": 100})
        out = []
        for entry in body.get("results") or []:
            token = str(entry.get("token") or "").strip()
            if not token:
                continue
            out.append({
                "template": token,
                "name": str(entry.get("name") or token),
                "carrier": str(entry.get("carrier") or "").strip().lower(),
                "length": entry.get("length"),
                "width": entry.get("width"),
                "height": entry.get("height"),
                "distance_unit": str(entry.get("distance_unit") or "in"),
            })
        out.sort(key=lambda t: (t["carrier"], t["name"]))
        return out


def _shippo_buy(self, *, rate_id: str, label_format: str = "PDF",
                idempotency_key: str = "") -> dict[str, Any]:
    """Buy the label for a rate.

    Shippo calls this a *transaction*. The `async: False` matters: the default queues the purchase and
    returns a transaction with no label on it, which reads as a silent failure.

    The idempotency key is the shipment id, which is derived from the order (shipment_id_for), so a
    double-clicked Buy and a retried request ask for the SAME label rather than buying two. A label is
    money that cannot be un-spent by refreshing the page.
    """
    payload = {"rate": str(rate_id or ""), "label_file_type": str(label_format or "PDF").upper(),
               "async": False}
    body = self._request("/transactions", payload=payload,
                         idempotency_key=str(idempotency_key or ""))
    status = str(body.get("status") or "").upper()
    if status != "SUCCESS":
        messages = body.get("messages") or []
        detail = "; ".join(str(m.get("text") or "") for m in messages if m.get("text"))[:300]
        raise ProviderError(detail or f"Shippo could not buy that label (status {status or 'unknown'}).")
    return {
        "provider": "shippo",
        "provider_transaction_id": str(body.get("object_id") or ""),
        "label_url": str(body.get("label_url") or ""),
        "tracking_number": str(body.get("tracking_number") or ""),
        # The provider hands us the tracking URL, which is why domain/carriers.py is needed only on the
        # MANUAL path.
        "tracking_url": str(body.get("tracking_url_provider") or ""),
        "label_format": str(body.get("label_file_type") or label_format or "PDF"),
    }


def _shippo_carrier_accounts(self) -> list[dict[str, Any]]:
    body = self._request("/carrier_accounts", params={"results": 50})
    return [
        {"account_id": str(entry.get("object_id") or ""),
         "carrier": str(entry.get("carrier") or ""),
         "active": bool(entry.get("active"))}
        for entry in (body.get("results") or [])
        if entry.get("object_id")
    ]


def _shippo_pickup(self, *, carrier_account: str, location: dict, transactions: list[str],
                   start_time: str, end_time: str) -> dict[str, Any]:
    """Book a carrier collection.

    `is_account_address` False plus an explicit address is the honest shape: the parcels are wherever the
    tenant actually packs them, which is not necessarily the address on the carrier account.
    """
    body = self._request("/pickups", payload={
        "carrier_account": str(carrier_account or ""),
        "location": {
            "building_location_type": str(location.get("building_location_type") or "Front Door"),
            "address": _shippo_address(location.get("address") or {}),
        },
        "transactions": [str(t) for t in transactions or []],
        "requested_start_time": str(start_time or ""),
        "requested_end_time": str(end_time or ""),
    })
    status = str(body.get("status") or "").upper()
    if status not in {"CONFIRMED", "SUCCESS"}:
        messages = body.get("messages") or []
        detail = "; ".join(str(m.get("text") or m) for m in messages)[:300]
        raise ProviderError(detail or f"The carrier did not confirm the pickup (status {status or '?'}).")
    return {
        "provider": "shippo",
        "pickup_id": str(body.get("object_id") or ""),
        "confirmation_code": str(body.get("confirmation_code") or ""),
        "status": status,
        "window_start": str(body.get("confirmed_start_time") or start_time),
        "window_end": str(body.get("confirmed_end_time") or end_time),
    }


def _shippo_manifest(self, *, carrier_account: str, ship_date: str, address_from: str,
                     transactions: list[str]) -> dict[str, Any]:
    """The end-of-day handover document.

    Shippo takes an address OBJECT ID here, not an inline address, which is why the caller has to have
    created one. The document covers ONE carrier, ONE ship date and ONE origin -- that constraint is the
    carrier's, not ours, and it is why the screen has to group before it offers this.
    """
    body = self._request("/manifests", payload={
        "carrier_account": str(carrier_account or ""),
        "shipment_date": str(ship_date or ""),
        "address_from": str(address_from or ""),
        "transactions": [str(t) for t in transactions or []],
    })
    status = str(body.get("status") or "").upper()
    if status in {"ERROR", "INVALID"}:
        messages = body.get("messages") or []
        detail = "; ".join(str(m.get("text") or m) for m in messages)[:300]
        raise ProviderError(detail or "The carrier rejected the manifest.")
    return {
        "provider": "shippo",
        "manifest_id": str(body.get("object_id") or ""),
        "status": status or "QUEUED",
        "document_url": str(body.get("documents") or [""])[0] if isinstance(body.get("documents"), list)
                        else str(body.get("document_url") or ""),
    }


def _shippo_validate(self, address: dict[str, Any]) -> dict[str, Any]:
    """Shippo validates on address CREATE, with `validate: true`, and answers in validation_results.

    A carrier refuses an undeliverable address at the counter, or -- worse -- accepts it, fails to
    deliver, and returns the parcel weeks later at the tenant's expense. Finding out before the label is
    bought is the entire point.
    """
    body = self._request("/addresses", payload={**_shippo_address(address), "validate": True})
    results = body.get("validation_results") if isinstance(body.get("validation_results"), dict) else {}
    messages = [str(m.get("text") or m) for m in (results.get("messages") or [])]
    is_valid = results.get("is_valid")
    return {
        "valid": bool(is_valid) if is_valid is not None else None,
        "messages": [m for m in messages if m][:5],
        # Shippo echoes a corrected address. Offered to the tenant, never applied silently: changing where
        # a parcel goes without being asked is worse than failing to deliver it.
        "normalized": {
            "street1": str(body.get("street1") or ""),
            "street2": str(body.get("street2") or ""),
            "city": str(body.get("city") or ""),
            "state": str(body.get("state") or ""),
            "postal_code": str(body.get("zip") or ""),
            "country": str(body.get("country") or ""),
        },
        "address_id": str(body.get("object_id") or ""),
    }


def _shippo_create_address(self, address: dict[str, Any]) -> str:
    """A stored address object, because /manifests takes an id rather than an inline address."""
    body = self._request("/addresses", payload=_shippo_address(address))
    return str(body.get("object_id") or "")


ShippoProvider.buy_label = _shippo_buy
ShippoProvider.carrier_accounts = _shippo_carrier_accounts
ShippoProvider.schedule_pickup = _shippo_pickup
ShippoProvider.create_manifest = _shippo_manifest
ShippoProvider.create_address = _shippo_create_address
ShippoProvider.validate_address = _shippo_validate


def _shippo_address(address: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": address.get("name", ""),
        "company": address.get("company", ""),
        "street1": address.get("street1", ""),
        "street2": address.get("street2", ""),
        "city": address.get("city", ""),
        "state": address.get("state", ""),
        "zip": address.get("postal_code", ""),
        "country": address.get("country", "US"),
        "phone": address.get("phone", ""),
        "email": address.get("email", ""),
    }


def _shippo_parcel(parcel: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "length": str(parcel.get("length", "")),
        "width": str(parcel.get("width", "")),
        "height": str(parcel.get("height", "")),
        "distance_unit": parcel.get("distance_unit", "in"),
        "weight": str(parcel.get("weight", "")),
        "mass_unit": parcel.get("mass_unit", "lb"),
    }
    # A carrier's own packaging, when the box the packer chose declares one. Flat-rate envelopes are
    # frequently the cheapest option for a soft pack, and sending dimensions alone means the carrier
    # prices it as a custom parcel and those rates are never quoted at all
    # (plans/SHIPPING_PROVIDERS.md, "Not everything ships in a box").
    template = str(parcel.get("template") or "").strip()
    if template:
        payload["template"] = template
    return payload


def _shippo_rate(rate: dict[str, Any]) -> dict[str, Any]:
    # Shippo's `servicelevel` arrives as an object, and sometimes as a bare string. The legacy adapter
    # handled both, which is the kind of knowledge that is expensive to rediscover and cheap to re-read.
    service = rate.get("servicelevel")
    if isinstance(service, dict):
        service_name = str(service.get("name") or "")
        service_token = str(service.get("token") or "")
    else:
        service_name = str(service or "")
        service_token = ""
    currency = str(rate.get("currency") or "usd").lower()
    return {
        "provider": "shippo",
        "rate_id": str(rate.get("object_id") or ""),
        "carrier": str(rate.get("provider") or ""),
        "service": service_name,
        "service_token": service_token,
        "amount": to_cents(rate.get("amount"), currency),
        "currency": currency,
        # Both axes. "Cheapest" is the wrong default for a seller who promised two-day delivery.
        "estimated_days": int(rate["estimated_days"]) if str(rate.get("estimated_days") or "").isdigit() else None,
        "attributes": [str(a) for a in (rate.get("attributes") or [])],
    }


class MockProvider(ShippingProvider):
    """Buys nothing, talks to nothing, and is how the whole flow is walked with no provider account.

    Deterministic on purpose: a test that asserts a price cannot depend on a carrier's live pricing.
    """

    name = "mock"

    def __init__(self, api_key: str = "", **_kwargs):
        self._api_key = api_key

    def test_connection(self) -> dict[str, Any]:
        return {"ok": True, "message": "Mock provider — no carrier is contacted.",
                "carriers": ["usps", "ups", "fedex"]}

    def rates(self, *, from_address: dict, to_address: dict, parcel: dict) -> list[dict[str, Any]]:
        pounds = Decimal(str(parcel.get("weight") or 1))
        base = {"usps": Decimal("6.50"), "ups": Decimal("9.10"), "fedex": Decimal("11.40")}
        out = []
        for index, (carrier, price) in enumerate(base.items()):
            out.append({
                "provider": "mock", "rate_id": f"mock_rate_{carrier}",
                "carrier": carrier, "service": "Ground", "service_token": f"{carrier}_ground",
                "amount": to_cents(price + pounds), "currency": "usd",
                "estimated_days": 5 - index, "attributes": ["CHEAPEST"] if carrier == "usps" else [],
            })
        return out


    def parcel_templates(self) -> list[dict[str, Any]]:
        return [
            {"template": "USPS_FlatRateSmallBox", "name": "USPS Small Flat Rate Box", "carrier": "usps",
             "length": 8.69, "width": 5.44, "height": 1.75, "distance_unit": "in"},
            {"template": "USPS_FlatRateMediumBox", "name": "USPS Medium Flat Rate Box", "carrier": "usps",
             "length": 11.25, "width": 8.75, "height": 6, "distance_unit": "in"},
        ]

    def carrier_accounts(self) -> list[dict[str, Any]]:
        return [{"account_id": f"mock_acct_{carrier}", "carrier": carrier, "active": True}
                for carrier in ("usps", "ups", "fedex")]

    def validate_address(self, address: dict) -> dict[str, Any]:
        """Deliverable unless the street says otherwise, so the undeliverable branch can be walked."""
        street = str((address or {}).get("street1") or "").lower()
        if "invalid" in street or "undeliverable" in street:
            return {"valid": False, "messages": ["Mock provider: this street is marked undeliverable."],
                    "normalized": {}, "address_id": "mock_addr_bad"}
        return {"valid": True, "messages": [], "normalized": {}, "address_id": "mock_addr_1"}

    def schedule_pickup(self, *, carrier_account: str, location: dict, transactions: list[str],
                        start_time: str, end_time: str) -> dict[str, Any]:
        return {"provider": "mock", "pickup_id": "mock_pickup_1", "confirmation_code": "MOCKCONF",
                "status": "CONFIRMED", "window_start": start_time, "window_end": end_time}

    def create_manifest(self, *, carrier_account: str, ship_date: str, address_from: str,
                        transactions: list[str]) -> dict[str, Any]:
        return {"provider": "mock", "manifest_id": "mock_manifest_1", "status": "SUCCESS",
                "document_url": "https://example.invalid/mock-manifest.pdf"}

    def create_address(self, address: dict[str, Any]) -> str:
        return "mock_address_1"

    def buy_label(self, *, rate_id: str, label_format: str = "PDF",
                  idempotency_key: str = "") -> dict[str, Any]:
        """Buys nothing. It exists so the entire flow -- select, rate, buy, notify -- can be walked end to
        end with no provider account, which is how F4 is proved before a tenant spends real postage."""
        token = str(rate_id or "mock_rate").rsplit("_", 1)[-1]
        return {
            "provider": "mock",
            "provider_transaction_id": f"mock_txn_{token}",
            "label_url": "https://example.invalid/mock-label.pdf",
            "tracking_number": f"MOCK{abs(hash(rate_id)) % 10**10:010d}",
            "tracking_url": "https://example.invalid/track",
            "label_format": str(label_format or "PDF").upper(),
        }


_PROVIDERS = {"shippo": ShippoProvider, "mock": MockProvider}


def provider_for(name: str, api_key: str, *, base_url: str = "", opener=None) -> ShippingProvider:
    """The adapter for a configured provider. Unknown names fail loudly rather than degrading to a mock --
    a silent mock would report a working connection for a provider that does not exist."""
    key = str(name or "").strip().lower()
    adapter = _PROVIDERS.get(key)
    if adapter is None:
        raise ProviderError(f"No adapter for shipping provider '{key or '(none)'}'.")
    if adapter is MockProvider:
        return adapter(api_key)
    return adapter(api_key, base_url=base_url, opener=opener)
