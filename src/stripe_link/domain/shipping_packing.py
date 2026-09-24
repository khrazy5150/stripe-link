"""Deciding what parcels an order ships in. Pure -- no I/O, no provider.

Weight is additive. **Dimensions are not.** Carriers bill `max(actual_weight, dimensional_weight)` where
dim weight is L x W x H / divisor, so three items in one carton cost neither three parcels nor one item.
Working out which boxes things actually fit into is 3D bin packing, which is NP-hard and not worth solving
properly for a seller shipping a handful of orders a day.

So this approximates, in the order the plan decided (plans/SHIPPING_PROVIDERS.md P1):

1. **Declared** -- one item whose tenant declared the box it ships in. They know their own operation and
   are not second-guessed.
2. **Packed** -- volume fit: sum the item volumes, add void fill, choose the smallest catalog box that
   clears it AND can physically hold the largest item.
3. **Per item** -- one parcel each. Used when anything does not fit, or when there is no catalog, or when
   items have no dimensions of their own. Over-estimates, which is the safe direction.

Shared by the label buyer, the price estimator and the carrier calculator, so it is built once: three
implementations of "what parcel is this" would disagree, and the one that priced the order would not be the
one that bought the label.
"""
from typing import Any

# Packing is not tessellation: real parcels have padding, and things do not interlock. 1.25 is the usual
# working number for void fill. It is the single biggest source of error here -- suspect it before the
# rates when estimates come out wrong.
DEFAULT_VOID_FILL = 1.25

# Packaging kinds. A carton has rigid walls; a padded mailer does not, and pricing one as the other is
# what makes the starter mailer close to unusable (plans/SHIPPING_PROVIDERS.md, "Not everything ships in
# a box").
BOX = "box"
SOFT_PACK = "soft_pack"

# How far a COMPRESSIBLE item may exceed a soft pack's nominal thickness. A bubble mailer's "1 inch" is
# its flat measurement; stuffed, it bulges. Bounded rather than ignored, because a 4-inch item does not go
# into a 1-inch mailer however soft it is -- and it is an approximation, so it is named and tunable like
# DEFAULT_VOID_FILL rather than buried in a comparison.
SOFT_PACK_THICKNESS_TOLERANCE = 3.0


def _dims(source: dict[str, Any] | None) -> tuple[float, float, float] | None:
    """Length/width/height from either naming this codebase uses, or None if incomplete."""
    source = source or {}
    values = []
    for keys in (("length", "length_in"), ("width", "width_in"), ("height", "height_in")):
        value = next((source[key] for key in keys if source.get(key) not in (None, "")), None)
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number <= 0:
            return None
        values.append(number)
    return (values[0], values[1], values[2])


def fits_inside(item: tuple[float, float, float], box: tuple[float, float, float], *,
                box_kind: str = BOX, compressible: bool = False) -> bool:
    """Whether an item fits a box in SOME orientation.

    Sorting both is the standard axis-aligned rotation check: a 10x2x2 item goes in a 3x3x11 box turned on
    its side, and volume alone would have said a 6x6x6 box was fine when it is not.

    **A soft pack holding a compressible item is the one exception**, and it is deliberately narrow. Its
    two LARGEST dimensions are still checked strictly -- a pouch cannot be longer than the envelope -- but
    the smallest is treated as CAPACITY rather than a wall, bounded by
    `SOFT_PACK_THICKNESS_TOLERANCE`.

    Both halves of that condition matter. Loosening `fits_inside` generally would let a rigid jar into a
    flat envelope, which fails at the counter after the label is paid for; and an 8x5x2 pouch failing a
    9x6x1 mailer on `2 > 1` is why the packer climbs to a carton today and overcharges every order
    containing one. The constraint has to get MORE precise, not looser.
    """
    item_sides = sorted(item)
    box_sides = sorted(box)
    if box_kind == SOFT_PACK and compressible:
        if not all(side <= wall for side, wall in zip(item_sides[1:], box_sides[1:])):
            return False
        return item_sides[0] <= box_sides[0] * SOFT_PACK_THICKNESS_TOLERANCE
    return all(side <= wall for side, wall in zip(item_sides, box_sides))


def _first_positive(*sources) -> float:
    for source in sources:
        try:
            value = float(source)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 0.0


def _weight(unit: dict[str, Any]) -> float:
    """What this thing weighs SHIPPED IN ITS OWN BOX.

    A DECLARED package's weight wins and is not added to the item's. The form asks for "Package Dimensions
    -> Weight (pounds)", which is the weight of the thing as shipped, box included -- adding the item's
    weight on top would bill the contents twice.
    """
    package = unit.get("package") or {}
    return _first_positive(package.get("weight"), unit.get("weight"), unit.get("weight_lb"))


def _item_weight(unit: dict[str, Any]) -> float:
    """What the thing weighs BARE, for when several share one box.

    Distinct from `_weight` because that number includes the item's own packaging, and the shared-box
    branch adds the shared box on top. Summing the packed weight per item billed the cardboard once per
    item: three 1 lb tubs (0.85 product + 0.15 box) quoted 3.0 + 0.35 = 3.35 lb against a true 2.9 --
    about 15% over on three items, growing with the count (found 2026-09-24).

    Falls back to the packed weight when no bare weight is recorded. That still over-estimates, but
    over-estimating is the safe direction -- a carrier refuses or re-bills an under-weight parcel after
    the label is paid for -- and it is what every product stored before `item_weight` existed will hit.
    """
    return _first_positive(unit.get("item_weight"), _weight(unit))


def _units(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per physical thing. Quantity 3 is three objects to pack, not one heavier one."""
    out = []
    for item in items or []:
        count = max(1, int(item.get("quantity") or 1))
        for _ in range(count):
            out.append(item)
    return out


def _parcel(dimensions, weight, *, distance_unit, mass_unit, box="", packed_from=(), strategy=""):
    length, width, height = dimensions
    return {
        "length": round(float(length), 2), "width": round(float(width), 2), "height": round(float(height), 2),
        "weight": round(max(float(weight), 0.01), 2),
        "distance_unit": distance_unit, "mass_unit": mass_unit,
        "box": box, "packed_from": list(packed_from), "strategy": strategy,
    }


def _per_item(units, *, distance_unit, mass_unit) -> list[dict[str, Any]]:
    """One parcel per thing: what actually happens for oversized goods, and the honest fallback when
    nothing else is known. Over-estimates rather than under-estimates."""
    parcels = []
    for unit in units:
        dimensions = _dims(unit.get("package")) or _dims(unit)
        if dimensions is None:
            continue
        parcels.append(_parcel(
            dimensions, _weight(unit),
            distance_unit=distance_unit, mass_unit=mass_unit,
            packed_from=[unit.get("product_id", "")], strategy="per_item",
        ))
    return parcels


def pack(
    items: list[dict[str, Any]],
    boxes: list[dict[str, Any]] | None = None,
    *,
    distance_unit: str = "in",
    mass_unit: str = "lb",
    void_fill: float = DEFAULT_VOID_FILL,
) -> list[dict[str, Any]]:
    """The parcels an order ships in.

    `items` carry `quantity`, `weight`, the item's own `length`/`width`/`height` when known, and an
    optional `package` -- the box the tenant declared for that product. All dimensions must already share
    `distance_unit`, and all weights `mass_unit`; converting units is the caller's job, not a silent
    guess made here.

    Returns [] when nothing is known rather than inventing a parcel: a made-up box buys a label at the
    wrong postage, which the carrier bills for or the package is returned for.
    """
    units = _units(items)
    if not units:
        return []

    # 0. Things that go in their own box, whatever else is in the order. A declared package is an
    #    EXCEPTION for what dimensions cannot predict -- something fragile needing void fill far beyond
    #    its size, a rolled poster, an item in manufacturer packaging -- so it must not swallow the rest
    #    of the order. Splitting here is what lets a ships-alone item and packable ones coexist; the old
    #    shape returned early and could not express that at all.
    alone = [unit for unit in units if unit.get("ships_alone") and _dims(unit.get("package"))]
    units = [unit for unit in units if unit not in alone]
    parcels = [
        _parcel(_dims(unit["package"]), _weight(unit), distance_unit=distance_unit, mass_unit=mass_unit,
                box=str((unit.get("package") or {}).get("name") or ""),
                packed_from=[unit.get("product_id", "")], strategy="declared")
        for unit in alone
    ]
    if not units:
        return parcels

    # 1. One thing left, and the tenant said what it ships in.
    if len(units) == 1:
        declared = _dims(units[0].get("package"))
        if declared:
            return parcels + [
                _parcel(declared, _weight(units[0]), distance_unit=distance_unit, mass_unit=mass_unit,
                        packed_from=[units[0].get("product_id", "")], strategy="declared")]

    catalog = [box for box in (boxes or []) if _dims(box)]
    item_dims = [_dims(unit) for unit in units]
    # 2. Volume fit -- only when every thing has a size of its own AND there are boxes to put them in.
    if catalog and all(item_dims):
        total_volume = sum(length * width * height for length, width, height in item_dims) * float(void_fill)
        # BARE weights: the shared box's own weight is added once, below.
        total_weight = sum(_item_weight(unit) for unit in units)
        candidates = []
        for box in catalog:
            box_dims = _dims(box)
            # A box has a weight limit as well as a size. USPS flat rate caps at 70 lb, and a carrier
            # refuses an over-weight parcel at the counter -- after the label is bought and paid for.
            limit = box.get("max_weight")
            if limit and total_weight + float(box.get("empty_weight") or 0) > float(limit):
                continue
            # Necessary, not sufficient: every item must physically fit this box, and the volumes must
            # clear. Two items that each fit can still fail to fit TOGETHER (two long rods in a flat box),
            # which is the approximation's known limit -- see Calibration in the plan.
            kind = str(box.get("kind") or BOX)
            if not all(
                fits_inside(dimension, box_dims, box_kind=kind,
                            compressible=bool(unit.get("compressible")))
                for dimension, unit in zip(item_dims, units)
            ):
                continue
            # A soft pack's capacity is not its nominal volume. If thickness is treated as capacity for
            # the FIT, it has to be for the volume too, or a mailer is judged able to hold a pouch it
            # cannot be said to have room for. Only when every item squashes: one rigid thing in the
            # envelope stops it bulging for anything.
            length, width, height = box_dims
            if kind == SOFT_PACK and all(unit.get("compressible") for unit in units):
                # Declare what it will MEASURE when stuffed, not the flat figure. Under-declaring
                # thickness is how a carrier re-bills dimensional weight after the label is bought.
                needed = total_volume / (length * width) if length and width else height
                height = min(max(height, needed), height * SOFT_PACK_THICKNESS_TOLERANCE)
                box_dims = (length, width, height)
            box_volume = length * width * height
            if box_volume + 1e-9 >= total_volume:
                candidates.append((box_volume, box, box_dims))
        if candidates:
            _, box, box_dims = min(candidates, key=lambda entry: entry[0])
            # A box is not weightless and the carrier bills the whole parcel.
            weight = total_weight + float(box.get("empty_weight") or 0)
            return parcels + [
                _parcel(box_dims, weight, distance_unit=distance_unit, mass_unit=mass_unit,
                        box=str(box.get("name") or ""),
                        packed_from=[unit.get("product_id", "") for unit in units], strategy="packed")]

    # 3. Nothing fit, no catalog, or no item dimensions.
    return parcels + _per_item(units, distance_unit=distance_unit, mass_unit=mass_unit)
