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
3. **Multi-box** -- several catalog boxes, first-fit-decreasing, when nothing holds the whole order but the
   catalog holds it in pieces. What a warehouse actually does, and the gap a BUNDLE lives in: without it a
   cart that outgrows one box fell to per-item parcels with no box, so a flat-rate-box price had nothing to
   look up and a bundle could not be quoted at all (plans/SHIPPING_ELEMENT.md phase 7).
4. **Per item** -- one parcel each. Used when anything fits no box at all, when there is no catalog, or when
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

    **Never less than the thing inside it**, which is arithmetic rather than a safety margin: a box cannot
    make its contents lighter. A real catalogue declared a 26.5 lb packed weight for a 37 lb scooter and
    a 1 lb packed weight for 2 lb of whey, inherited from a builder that wrote a default package onto
    every physical product; the declared figure outranked the item's own, so those parcels were rated
    light and the carrier would have re-billed the difference weeks later (found 2026-10-06).

    The bare weight is also the last fallback, so a product with no declared package still has a weight.
    Zero is the one answer a parcel must never have -- a carrier refuses a zero-weight label or re-bills
    it after it is paid for -- and zero is what this returned before the default package stopped
    answering for everything.
    """
    package = unit.get("package") or {}
    packed = _first_positive(package.get("weight"), unit.get("weight"), unit.get("weight_lb"))
    return max(packed, _first_positive(unit.get("item_weight")))


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


def _parcel(dimensions, weight, *, distance_unit, mass_unit, box="", packed_from=(), strategy="",
            template=""):
    length, width, height = dimensions
    parcel = {
        "length": round(float(length), 2), "width": round(float(width), 2), "height": round(float(height), 2),
        "weight": round(max(float(weight), 0.01), 2),
        "distance_unit": distance_unit, "mass_unit": mass_unit,
        "box": box, "packed_from": list(packed_from), "strategy": strategy,
    }
    # Carried from the chosen box to the provider. Omitted rather than emptied, so a parcel dict without
    # carrier packaging looks exactly as it always has.
    if template:
        parcel["template"] = str(template)
    return parcel


def box_shortfall(units, boxes, chosen_box_name: str) -> dict[str, Any] | None:
    """Why a smaller box was not used: the item that would not fit it, and by how much. `None` otherwise.

    Purely explanatory -- it changes no packing decision and is computed only when someone asks.

    It exists because a correct answer can look exactly like a bug. A single protein shaker bottle rated
    as a 14x11x8 Large box, which a tenant reasonably reported as broken (2026-10-05). The packer was
    right: the bottle is 10.2in tall and their Medium box's longest side is 10in, so it misses by **two
    tenths of an inch** and the Large is the only box it fits. Nothing on screen could say that, so the
    only available conclusion was that the software was wrong.

    Reported against the largest box SMALLER than the one chosen, because that is the one a tenant would
    have expected and the one worth knowing about: it turns "why is this in a huge box" into "your Medium
    box is 0.2in too short for your best-selling bottle", which is something they can act on -- buy taller
    boxes, or re-measure an item whose cap they counted twice.
    """
    chosen = next((box for box in boxes or [] if str(box.get("name") or "") == str(chosen_box_name)), None)
    chosen_dims = _dims(chosen) if chosen else None
    if not chosen_dims:
        return None

    def volume(dims):
        return dims[0] * dims[1] * dims[2]

    smaller = []
    for box in boxes or []:
        dims = _dims(box)
        if dims and volume(dims) < volume(chosen_dims):
            smaller.append((box, dims))
    if not smaller:
        return None
    # The largest of the smaller boxes -- the near miss, not the hopeless one.
    box, box_dims = max(smaller, key=lambda pair: volume(pair[1]))

    worst = None
    for unit in units or []:
        dims = _dims(unit)
        if not dims:
            continue
        if fits_inside(dims, box_dims, compressible=bool(unit.get("compressible"))):
            continue
        # BY HOW MUCH, measured the way the fit test measures: both sorted, compared axis by axis, and
        # the largest overhang is the one that decides it.
        over = max(side - wall for side, wall in zip(sorted(dims), sorted(box_dims)))
        if over <= 0:
            continue
        if worst is None or over > worst["over_by"]:
            worst = {"product_id": str(unit.get("product_id") or ""),
                     "longest_in": max(dims), "over_by": round(over, 2),
                     "box": str(box.get("name") or ""),
                     "box_longest_in": max(box_dims)}
    return worst


def _per_item(units, *, distance_unit, mass_unit) -> list[dict[str, Any]]:
    """One parcel per thing: what actually happens for oversized goods, and the honest fallback when
    nothing else is known. Over-estimates rather than under-estimates."""
    parcels = []
    for unit in units:
        # The ITEM's own size, never the declared package. A `ships_alone` unit with a declared box has
        # already been taken by strategy 0; anything still here reaching for `package` would be the same
        # unmeasured-default charge strategy 1 was removed for -- and this one preferred the declared box
        # over the item's real dimensions, which is the inversion backwards.
        dimensions = _dims(unit)
        if dimensions is None:
            continue
        parcels.append(_parcel(
            dimensions, _weight(unit),
            distance_unit=distance_unit, mass_unit=mass_unit,
            packed_from=[unit.get("product_id", "")], strategy="per_item",
        ))
    return parcels


def _best_box(units: list[dict[str, Any]], catalog: list[dict[str, Any]], *,
              void_fill: float = DEFAULT_VOID_FILL):
    """The smallest catalog box that holds ALL of `units`, or None. `(box, dims, weight)` when it does.

    Extracted from the volume-fit strategy so multi-box packing reuses the identical test rather than
    implementing fit a second way -- this module's docstring warns that two implementations of "what parcel
    is this" would disagree, and the one that priced the order would not be the one that bought the label.
    """
    item_dims = [_dims(unit) for unit in units]
    if not units or not all(item_dims):
        return None
    total_volume = sum(length * width * height for length, width, height in item_dims) * float(void_fill)
    # BARE weights: the shared box's own weight is added once, at the end.
    total_weight = sum(_item_weight(unit) for unit in units)
    candidates = []
    for box in catalog:
        box_dims = _dims(box)
        # A box has a weight limit as well as a size. USPS flat rate caps at 70 lb, and a carrier refuses an
        # over-weight parcel at the counter -- after the label is bought and paid for.
        limit = box.get("max_weight")
        if limit and total_weight + float(box.get("empty_weight") or 0) > float(limit):
            continue
        # Necessary, not sufficient: every item must physically fit this box, and the volumes must clear. Two
        # items that each fit can still fail to fit TOGETHER (two long rods in a flat box), which is the
        # approximation's known limit -- see Calibration in the plan.
        kind = str(box.get("kind") or BOX)
        if not all(
            fits_inside(dimension, box_dims, box_kind=kind, compressible=bool(unit.get("compressible")))
            for dimension, unit in zip(item_dims, units)
        ):
            continue
        # A soft pack's capacity is not its nominal volume. If thickness is treated as capacity for the FIT,
        # it has to be for the volume too, or a mailer is judged able to hold a pouch it cannot be said to
        # have room for. Only when every item squashes: one rigid thing stops it bulging for anything.
        length, width, height = box_dims
        if kind == SOFT_PACK and all(unit.get("compressible") for unit in units):
            # Declare what it will MEASURE when stuffed, not the flat figure. Under-declaring thickness is
            # how a carrier re-bills dimensional weight after the label is bought.
            needed = total_volume / (length * width) if length and width else height
            height = min(max(height, needed), height * SOFT_PACK_THICKNESS_TOLERANCE)
            box_dims = (length, width, height)
        box_volume = length * width * height
        if box_volume + 1e-9 >= total_volume:
            candidates.append((box_volume, box, box_dims))
    if not candidates:
        return None
    _, box, box_dims = min(candidates, key=lambda entry: entry[0])
    # A box is not weightless and the carrier bills the whole parcel.
    return box, box_dims, total_weight + float(box.get("empty_weight") or 0)


def _multi_box_groups(units: list[dict[str, Any]], catalog: list[dict[str, Any]], *,
                      void_fill: float = DEFAULT_VOID_FILL):
    """Partition an order into several catalog boxes. `[(group, box, dims, weight), ...]` or `[]`.

    First-fit-decreasing: biggest item first, into the first open parcel that still holds it, else a new
    parcel. Classic bin packing, approximated for the same reason everything here is -- 3D bin packing is
    NP-hard and not worth solving properly for a seller shipping a handful of orders a day.

    Returns `[]` when any single item fits no box at all: something oversized belongs in the per-item
    fallback, which is honest about having no box for it, rather than in a parcel list that implies one.
    """
    if not units or not catalog:
        return []
    ordered = sorted(units, key=lambda unit: -(lambda d: d[0] * d[1] * d[2])(_dims(unit) or (0, 0, 0)))
    groups: list[list[dict[str, Any]]] = []
    for unit in ordered:
        if not _best_box([unit], catalog, void_fill=void_fill):
            # One thing the catalog cannot hold. Splitting the rest into boxes and leaving this one homeless
            # would report a parcel count nobody can actually post.
            return []
        for group in groups:
            if _best_box(group + [unit], catalog, void_fill=void_fill):
                group.append(unit)
                break
        else:
            groups.append([unit])

    packed = []
    for group in groups:
        chosen = _best_box(group, catalog, void_fill=void_fill)
        if not chosen:  # pragma: no cover - a group is only built from fits that already passed
            return []
        box, box_dims, weight = chosen
        packed.append((group, box, box_dims, weight))
    # One group is not multi-box: strategy 2 already tried that and failed, so re-reporting it here would
    # claim a different answer to the same question.
    return packed if len(packed) > 1 else []


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

    # 1. REMOVED 2026-10-01 -- the declared-box fallback for a lone unmeasured item.
    #
    #    It read `fulfillment.dimensions` whenever an item had no size of its own, whether or not the
    #    tenant had ticked "always ships in its own box". That turned a leftover default into a priced
    #    parcel: dev data carried the identical 10x8x4 @ 1 lb on a paint set, a shaker bottle and whey
    #    protein, and a real buyer was quoted and charged $6.57 rated from it. The number looked
    #    legitimate, which is why nobody questioned it.
    #
    #    A declared box is now what strategy 0 says it is and nothing else: an EXCEPTION the tenant
    #    declares by ticking `ships_alone`. An item with no measurements yields NO parcel, which the
    #    callers turn into free shipping rather than a price nobody can stand behind
    #    (plans/SHIPPING_BEYOND_THE_FIRST_SALE.md P0a). This finishes the inversion
    #    plans/SHIPPING_PROVIDERS.md already describes rather than leaving a path that contradicts it.

    catalog = [box for box in (boxes or []) if _dims(box)]
    item_dims = [_dims(unit) for unit in units]
    # 2. Volume fit -- only when every thing has a size of its own AND there are boxes to put them in.
    if catalog and all(item_dims):
        chosen = _best_box(units, catalog, void_fill=void_fill)
        if chosen:
            box, box_dims, weight = chosen
            return parcels + [
                _parcel(box_dims, weight, distance_unit=distance_unit, mass_unit=mass_unit,
                        box=str(box.get("name") or ""), template=str(box.get("template") or ""),
                        packed_from=[unit.get("product_id", "") for unit in units], strategy="packed")]

        # 2b. MULTI-BOX. Nothing holds the whole order, but the catalog may hold it in several parcels --
        #     which is what a warehouse actually does, and what the per-item fallback below cannot express:
        #     it returns parcels with NO box, so a flat-rate-box price has nothing to look up and a bundle
        #     cannot be quoted at all (plans/SHIPPING_ELEMENT.md phase 7).
        #
        #     First-fit-decreasing: biggest item first, into the first open parcel that still holds it, else
        #     a new parcel. An approximation like everything else here -- the same volume-plus-fit test as
        #     strategy 2, so the same known limit applies (two long rods in a flat box). It reuses
        #     `_best_box` rather than testing fit a second way, because this module's own docstring warns
        #     that two implementations of "what parcel is this" would disagree.
        groups = _multi_box_groups(units, catalog, void_fill=void_fill)
        if groups:
            return parcels + [
                _parcel(box_dims, weight, distance_unit=distance_unit, mass_unit=mass_unit,
                        box=str(box.get("name") or ""), template=str(box.get("template") or ""),
                        packed_from=[unit.get("product_id", "") for unit in group], strategy="multi_box")
                for group, box, box_dims, weight in groups]

    # 3. Nothing fit, no catalog, or no item dimensions.
    return parcels + _per_item(units, distance_unit=distance_unit, mass_unit=mass_unit)
