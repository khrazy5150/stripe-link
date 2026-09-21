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

    def _request(self, path: str, *, payload: dict | None = None, params: dict | None = None) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={
                "Authorization": f"ShippoToken {self._api_key}",
                "Content-Type": "application/json",
            },
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
    return {
        "length": str(parcel.get("length", "")),
        "width": str(parcel.get("width", "")),
        "height": str(parcel.get("height", "")),
        "distance_unit": parcel.get("distance_unit", "in"),
        "weight": str(parcel.get("weight", "")),
        "mass_unit": parcel.get("mass_unit", "lb"),
    }


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
