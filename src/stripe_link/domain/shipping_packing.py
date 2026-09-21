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


def fits_inside(item: tuple[float, float, float], box: tuple[float, float, float]) -> bool:
    """Whether an item fits a box in SOME orientation.

    Sorting both is the standard axis-aligned rotation check: a 10x2x2 item goes in a 3x3x11 box turned on
    its side, and volume alone would have said a 6x6x6 box was fine when it is not.
    """
    return all(side <= wall for side, wall in zip(sorted(item), sorted(box)))


def _weight(unit: dict[str, Any]) -> float:
    """What this thing weighs when it ships.

    A DECLARED package's weight wins and is not added to the item's. The form asks for "Package Dimensions
    -> Weight (pounds)", which is the weight of the thing as shipped, box included -- adding the item's
    weight on top would bill the contents twice.
    """
    package = unit.get("package") or {}
    for source in (package.get("weight"), unit.get("weight"), unit.get("weight_lb")):
        try:
            value = float(source)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 0.0


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

    # 1. One thing, and the tenant said what it ships in.
    if len(units) == 1:
        declared = _dims(units[0].get("package"))
        if declared:
            return [_parcel(declared, _weight(units[0]), distance_unit=distance_unit, mass_unit=mass_unit,
                            packed_from=[units[0].get("product_id", "")], strategy="declared")]

    catalog = [box for box in (boxes or []) if _dims(box)]
    item_dims = [_dims(unit) for unit in units]
    # 2. Volume fit -- only when every thing has a size of its own AND there are boxes to put them in.
    if catalog and all(item_dims):
        total_volume = sum(length * width * height for length, width, height in item_dims) * float(void_fill)
        total_weight = sum(_weight(unit) for unit in units)
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
            if not all(fits_inside(dimension, box_dims) for dimension in item_dims):
                continue
            box_volume = box_dims[0] * box_dims[1] * box_dims[2]
            if box_volume + 1e-9 >= total_volume:
                candidates.append((box_volume, box, box_dims))
        if candidates:
            _, box, box_dims = min(candidates, key=lambda entry: entry[0])
            # A box is not weightless and the carrier bills the whole parcel.
            weight = total_weight + float(box.get("empty_weight") or 0)
            return [_parcel(box_dims, weight, distance_unit=distance_unit, mass_unit=mass_unit,
                            box=str(box.get("name") or ""),
                            packed_from=[unit.get("product_id", "") for unit in units], strategy="packed")]

    # 3. Nothing fit, no catalog, or no item dimensions.
    return _per_item(units, distance_unit=distance_unit, mass_unit=mass_unit)
