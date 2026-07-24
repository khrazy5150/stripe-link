"""Category → specific LocalBusiness ``@type`` table (plans/LOCAL_SEO_SIGNALS.md item #1).

The Site's ``organization.entity_type`` is one of a small set of *broad* schema.org buckets
(HealthAndBeautyBusiness, Store, …) that a tenant hand-picks. That is enough to gate local-SEO
signals, but the JSON-LD is stronger when it names the *specific* type — ``Dentist`` beats
``HealthAndBeautyBusiness``, ``Plumber`` beats ``HomeAndConstructionBusiness``.

``organization.business_type`` (optional) carries that specific type. When set, the renderer emits it
as the Organization ``@type``; ``entity_type`` remains the broad fallback and the local-business gate.

Every specific type here IS a LocalBusiness (or a Medical/Store subtype that is itself local), so a
set ``business_type`` alone marks a page as a local business for alt/figcaption purposes.

Each type is grouped under the broad ``entity_type`` bucket it belongs to *in this picker* — which is
not always its schema.org parent (schema.org files Dentist under MedicalBusiness, but we bucket it
under HealthAndBeautyBusiness because that is the broad value tenants pick). The emitted ``@type`` is
the specific, schema.org-correct string regardless of the bucket.
"""
from __future__ import annotations

# Ordered so the dashboard can render an optgroup per broad bucket. Every ``type`` is a real
# schema.org LocalBusiness subtype. ``label`` is the human-facing group heading.
BUSINESS_TYPE_GROUPS: list[dict[str, object]] = [
    {
        "parent": "HealthAndBeautyBusiness",
        "label": "Health & beauty",
        "types": [
            "BeautySalon", "DaySpa", "HairSalon", "NailSalon", "HealthClub", "TattooParlor",
            "Dentist", "MedicalClinic", "Optician", "Physician",
        ],
    },
    {
        "parent": "HomeAndConstructionBusiness",
        "label": "Home & construction",
        "types": [
            "Plumber", "Electrician", "HVACBusiness", "RoofingContractor", "HousePainter",
            "Locksmith", "MovingCompany", "GeneralContractor",
        ],
    },
    {
        "parent": "FoodEstablishment",
        "label": "Food & drink",
        "types": ["Restaurant", "CafeOrCoffeeShop", "Bakery", "BarOrPub", "IceCreamShop", "Winery"],
    },
    {
        "parent": "ProfessionalService",
        "label": "Professional services",
        "types": [
            "AccountingService", "LegalService", "Attorney", "Notary", "RealEstateAgent",
            "InsuranceAgency", "AutoRepair", "TravelAgency",
        ],
    },
    {
        "parent": "Store",
        "label": "Stores & retail",
        "types": [
            "ClothingStore", "GroceryStore", "JewelryStore", "PetStore", "HardwareStore",
            "BookStore", "FurnitureStore", "ShoeStore", "ToyStore", "Florist", "ConvenienceStore",
        ],
    },
    {
        "parent": "LocalBusiness",
        "label": "Other local",
        "types": ["ChildCare", "DryCleaningOrLaundry", "SelfStorage", "EntertainmentBusiness"],
    },
]

# Flat set of every recognized specific type (validation) and its picker bucket (dashboard grouping).
BUSINESS_TYPES: frozenset[str] = frozenset(
    t for g in BUSINESS_TYPE_GROUPS for t in g["types"]  # type: ignore[misc]
)
BUSINESS_TYPE_PARENT: dict[str, str] = {
    t: str(g["parent"]) for g in BUSINESS_TYPE_GROUPS for t in g["types"]  # type: ignore[misc]
}


def resolve_entity_type(entity_type: str, business_type: str) -> str:
    """The schema.org ``@type`` to emit: the specific ``business_type`` when it is a recognized subtype,
    otherwise the broad ``entity_type`` (or ``Organization`` when neither is set)."""
    specific = str(business_type or "").strip()
    if specific in BUSINESS_TYPES:
        return specific
    return str(entity_type or "").strip() or "Organization"
