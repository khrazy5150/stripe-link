"""One carrier credential per Stripe mode, so TEST never spends real postage.

**The defect this closes.** `ShippingConfig` held a single `provider.api_key_ref`, keyed on tenant alone,
with no mode axis anywhere in the shipping path: `shipping_config_repository()` takes no mode and
`provider_for(name, api_key)` is never given one. So the dashboard's TEST/LIVE toggle moved products and
orders and left the carrier key exactly where it was. Two consequences, both reported by the author
2026-10-11:

1. **A tenant in TEST mode who buys a label with a live key is really charged.** The screen says TEST;
   the money path has no idea. Shippo's own test keys mint clearly-marked test labels that cost nothing,
   which is the protection the toggle appeared to offer and did not.
2. **Saving a test key destroyed the live one.** One slot. A tenant live for months who tries test mode
   loses the credential their real shipping depends on, silently, with no way to get it back.

The `test_mode` checkbox did not help: it is saved, displayed, and read by nothing. It could not have
worked anyway -- Shippo uses one base URL and decides the environment from the key's own prefix.

**The provider stays shared and only the credential splits.** A tenant's warehouse address, parcel
defaults and label format are the same facts in both modes, and nobody uses Shippo for test and EasyPost
for live. Making the whole document mode-scoped would force them to re-enter their address to flip a
toggle, which is how a safety feature becomes the thing people route around.

**The KMS encryption context is deliberately NOT mode-scoped** (`SECRET_MODE = "shipping"`). It is part of
the ciphertext's identity, so changing it per mode would make every key already stored undecryptable.
"""
from __future__ import annotations

from typing import Any

MODES = ("test", "live")

# How each provider spells the environment in the key itself. Shippo is the only one wired today; the
# others are here so the check is a lookup rather than a special case when they arrive.
KEY_PREFIXES: dict[str, dict[str, tuple[str, ...]]] = {
    "shippo": {"test": ("shippo_test_",), "live": ("shippo_live_",)},
    "easypost": {"test": ("EZTK",), "live": ("EZAK",)},
}


def normalize_mode(value: Any) -> str:
    """`test` unless explicitly `live` — the same fail-safe direction as `normalize_stripe_mode`.

    Guessing `live` on an unreadable value would be guessing toward spending money.
    """
    return "live" if str(value or "").strip().lower() == "live" else "test"


def key_slot(provider: dict[str, Any] | None, mode: str) -> dict[str, Any]:
    """The stored credential block for one mode. `{}` when that mode has never been configured."""
    keys = (provider or {}).get("keys")
    if not isinstance(keys, dict):
        return {}
    slot = keys.get(normalize_mode(mode))
    return dict(slot) if isinstance(slot, dict) else {}


def with_key_slot(provider: dict[str, Any] | None, mode: str, slot: dict[str, Any] | None) -> dict[str, Any]:
    """`provider` with one mode's credential block replaced. The OTHER mode is never touched.

    That is the entire point: saving a test key must not be able to reach the live one.
    """
    out = dict(provider or {})
    keys = dict(out.get("keys") or {})
    mode = normalize_mode(mode)
    if slot:
        keys[mode] = dict(slot)
    else:
        keys.pop(mode, None)
    out["keys"] = keys
    return out


def mode_of_key(provider_name: str, plaintext: str) -> str:
    """Which environment a freshly-typed key belongs to, from its own prefix. `""` when unknowable.

    Shippo and EasyPost both say so in the key, which makes a mismatch catchable at the moment somebody
    can still fix it -- rather than at the moment a real label is bought in a window marked TEST.
    """
    prefixes = KEY_PREFIXES.get(str(provider_name or "").strip().lower())
    if not prefixes:
        return ""
    for mode, starts in prefixes.items():
        if any(str(plaintext or "").startswith(start) for start in starts):
            return mode
    return ""


def key_mismatch(provider_name: str, plaintext: str, mode: str) -> str:
    """A refusal message when the key contradicts the mode it is being saved under, else `""`.

    Refused rather than silently accepted, because the two ways of being wrong are not symmetric: a live
    key saved under test is money waiting to be spent by somebody who believes they are safe.
    """
    found = mode_of_key(provider_name, plaintext)
    wanted = normalize_mode(mode)
    if not found or found == wanted:
        return ""
    return (f"That looks like a {found} key, but you are saving it to {wanted} mode. "
            f"Switch the dashboard to {found} mode, or paste your {wanted} key instead.")


def legacy_ref(provider: dict[str, Any] | None) -> str:
    """The single pre-split `api_key_ref`, if this config still carries one."""
    return str((provider or {}).get("api_key_ref") or "").strip()


def adopt_legacy(provider: dict[str, Any] | None, mode: str, plaintext: str) -> dict[str, Any] | None:
    """The legacy key moved into its rightful mode slot, or None when it does not belong to `mode`.

    A config written before the split has one key and no record of which environment it was for. The key
    itself usually knows, so it is classified by prefix and adopted into that slot only. A live key
    therefore stays invisible in test mode, which is the whole fix.

    **An unrecognisable prefix is withheld from NEITHER mode**, and that asymmetry is the whole of the
    design. Refuse only what can be POSITIVELY identified as wrong:

      * a `shippo_live_` key asked for in test mode -- known wrong, withheld. This is the actual risk,
        because Shippo is the only provider wired and its keys always say which they are.
      * a key whose provider does not advertise the environment -- unknowable, so left exactly as it
        behaved before. "I cannot tell what this is" is not the claim "this is the wrong one", and only
        the second justifies breaking a tenant's working setup.

    Two earlier versions got this wrong in both directions and are recorded so nobody repeats them.
    Refusing everything unclassifiable stopped real shipping for anyone whose key lacked a prefix.
    Treating it as live instead broke the same tenants in test mode for a risk they may not have had.
    """
    provider = provider or {}
    found = mode_of_key(provider.get("name"), plaintext)
    if found and found != normalize_mode(mode):
        return None
    return {
        "api_key_ref": legacy_ref(provider),
        # Carried across rather than reset: the key has not changed, so what we knew about it still holds.
        "connection_status": provider.get("connection_status") or "untested",
        **({"last_tested_at": provider["last_tested_at"]}
           if provider.get("last_tested_at") is not None else {}),
    }


def configured_modes(provider: dict[str, Any] | None) -> list[str]:
    """Which modes have a key, for a dashboard that should say so before a tenant discovers it."""
    return [mode for mode in MODES if key_slot(provider, mode).get("api_key_ref")]
