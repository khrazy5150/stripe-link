"""Which shipping providers a tenant may actually choose.

The schema has always listed five provider names. None of them was ever wired, so the dashboard offered a
menu of four carriers plus a mock and every one of them did nothing.

Availability is decided HERE, in code, rather than in platform config, and that is deliberate. "This
provider is available" means "its adapter exists and has been exercised against the real API". A config
flag could switch on a provider whose adapter has never run -- which is the exact failure this gate exists
to prevent, wearing the costume of a feature toggle.

Only two of the four can be verified end to end without spending money:

  - Shippo   -- the API KEY carries test mode; a test token buys unlimited free test labels.
  - EasyPost -- same shape; free test key on signup.
  - ShipStation -- test mode is a request flag (`testLabel`), but the API needs a real account, and there
    is no free tier to get one from.
  - Easyship -- unknown. The legacy adapter reads `test_mode` into its constructor and never applies it to
    a single request, so nobody has established how its sandbox is even addressed.

Building the two we cannot exercise would produce code that looks finished and has never been true. That
has cost this codebase twice already: every layer green against fakes, and the real API refusing the
result. So they stay off until someone can hold a working key.

To promote a provider: build its adapter, exercise it against the real API, then add it to GA_PROVIDERS --
in that order.
"""
from typing import Any

# Every name the schema permits to be STORED. Unchanged, so a document written before this gate existed
# still validates; availability is a separate question from document shape.
ALL_PROVIDERS = ("shippo", "easypost", "shipstation", "easyship", "mock")

# Generally available: a tenant may pick these in any environment.
GA_PROVIDERS = ("shippo",)

# Off-prod only. `mock` buys nothing and talks to nothing, so it is how the whole flow -- config, rates,
# labels, fulfilment -- can be walked end to end with no provider account and no spend at all. Exposing it
# to live tenants would only offer them a shipping provider that does not ship.
NON_PROD_PROVIDERS = ("mock",)


class ProviderNotAvailable(ValueError):
    """A provider the schema allows but that is not wired (or not wired here) yet."""


def selectable_providers(environment: str = "") -> tuple[str, ...]:
    """The providers a tenant may choose in `environment`."""
    if str(environment or "").strip().lower() == "prod":
        return GA_PROVIDERS
    return GA_PROVIDERS + NON_PROD_PROVIDERS


def assert_provider_available(name: Any, environment: str = "") -> None:
    """Refuse a provider that exists in the schema but has no working adapter.

    Names the alternatives, because "Shipping provider is invalid" for a name the dashboard itself offered
    is a dead end for whoever hits it.
    """
    provider = str(name or "").strip().lower()
    allowed = selectable_providers(environment)
    if provider in allowed:
        return
    if provider in ALL_PROVIDERS:
        raise ProviderNotAvailable(
            f"Shipping provider '{provider}' is not available yet. "
            f"Currently available: {', '.join(allowed)}."
        )
    raise ProviderNotAvailable(f"Shipping provider '{provider}' is not a provider this platform supports.")
