# Business type: a real vocabulary, and one list instead of three

Proposed 2026-11-10. Design only — no code yet. Prompted by a tenant whose Google Business Profile
category is **"Massage Therapist"**, which the picker could not express.

## The question that started it, and the answer

*Can we put Google Business Profile categories in the Specific type dropdown, or make it a free-text
autocomplete like product categories?*

**No to both, for the same reason.** That field emits the schema.org `@type` in JSON-LD
(`resolve_entity_type`). schema.org is a **closed vocabulary**: `"@type": "Massage therapist"` is not a
type, it is a string, and invalid markup costs rich results rather than sharpening them. Product
categories are *our own* taxonomy, so anything a tenant types is valid by construction — that is exactly
why free text is right there and wrong here.

**There is no massage type in schema.org at all** (checked against the vocabulary, not assumed):
`HealthAndBeautyBusiness` has exactly six subtypes — BeautySalon, DaySpa, HairSalon, HealthClub,
NailSalon, TattooParlor. `MedicalBusiness` has 26, the nearest being `Physiotherapy`.

**A GBP category and a schema.org `@type` are not supposed to match.** They are different vocabularies
feeding different systems — GBP drives Maps and the local pack, `@type` drives rich results. Most GBP
categories have no schema.org equivalent, so a mismatch is the normal state. Google penalises markup
that is INACCURATE, not markup that is less specific than a GBP category.

So the rule for tenants is **pick the most specific type that is TRUE**, and the broad bucket alone is a
legitimate answer. `resolve_entity_type` already falls back to the broad `entity_type`, and
`_org_is_local` already gates on it, so choosing "General" keeps every local-SEO signal working.

**The GBP category is still worth having — as its own field.** It belongs with
plans/BUSINESS_PROFILE_AND_GBP.md, where free text or an autocomplete IS right, because nothing
validates it against a closed vocabulary. Two fields, two purposes; conflating them is what makes this
question feel unanswerable.

## The problem worth fixing first: three lists, no alarm

The broad local-business types are written out by hand in three places:

| Where | Entries | Used for |
|---|---|---|
| `SITE_ENTITY_TYPES` (`documents.py`) | 8 | validation |
| `_LOCAL_BUSINESS_TYPES` (`html.py`) | 6 | the local-SEO gate (alt text, figcaption NAP) |
| `_GOOGLE_DEFAULT_ENTITY_TYPES` (`reviews.py`) | 5 | the review link |

Adding a vertical means editing all three, **and nothing fails if one is missed**: the new broad type
validates, saves, renders — and silently is not a local business, so the signals it was chosen for stop.
An absence that reads as "not local" rather than as an error (`feedback_absence_reads_as_safety`).

**Derive the other two from one source** before adding anything. The natural home is
`domain/business_types.py`, which already owns the specific types and their buckets: it should also own
the broad set and which of those are local. The review-link set is a genuine subset (OnlineStore and
Organization are not local), so it stays a filter over the one list rather than a fourth copy.

## Then: the list a local business can actually find itself in

Today's picker offers ~47 specific types under 6 buckets, and whole verticals cannot be expressed —
there is no broad type for medical, automotive, lodging, sport, entertainment or financial, so a
physiotherapist, a hotel or a gym has no honest answer at either level.

Proposed broad buckets to add (all real schema.org `LocalBusiness` subtypes):
`MedicalBusiness`, `AutomotiveBusiness`, `LodgingBusiness`, `SportsActivityLocation`,
`EntertainmentBusiness`, `FinancialService`.

Specific types to add, read off schema.org rather than invented:

* **MedicalBusiness** (26): Audiology, CommunityHealth, Dentist, Dermatology, DietNutrition, Emergency,
  Geriatric, Gynecologic, MedicalClinic, Midwifery, Nursing, Obstetric, Oncologic, Ophthalmology,
  Optician, Optometric, Otolaryngologic, Pediatric, Pharmacy, Physician, **Physiotherapy**,
  PlasticSurgery, Podiatric, PrimaryCare, Psychiatric, PublicHealth
* **AutomotiveBusiness** (9): AutoBodyShop, AutoDealer, AutoPartsStore, AutoRental, AutoRepair, AutoWash,
  GasStation, MotorcycleDealer, MotorcycleRepair
* **LodgingBusiness** (7): BedAndBreakfast, Campground, Hostel, Hotel, Motel, Resort, VacationRental
* **SportsActivityLocation** (9): BowlingAlley, ExerciseGym, GolfCourse, HealthClub, PublicSwimmingPool,
  SkiResort, SportsClub, StadiumOrArena, TennisComplex
* **EntertainmentBusiness** (7): AdultEntertainment, AmusementPark, ArtGallery, Casino, ComedyClub,
  MovieTheater, NightClub
* **FinancialService** (4): AccountingService, AutomatedTeller, BankOrCreditUnion, InsuranceAgency
* **Store** — the full 30, where we currently offer 11 (adds AutoPartsStore, BikeStore, ComputerStore,
  DepartmentStore, ElectronicsStore, GardenStore, HobbyShop, HomeGoodsStore, LiquorStore,
  MensClothingStore, MobilePhoneStore, MovieRentalStore, MusicStore, OfficeEquipmentStore, OutletStore,
  PawnShop, SportingGoodsStore, TireShop, WholesaleStore)
* **FoodEstablishment** — adds Brewery, Distillery, FastFoodRestaurant

Two of these already appear in our table under a different bucket (`AutoRepair` under
ProfessionalService, `HealthClub` under Health & beauty). The existing docstring says bucketing need not
follow schema.org parentage — but a type must appear **once**, or the picker shows it twice and the
parent map becomes ambiguous.

## Not in scope

**`AdultEntertainment`** is a valid schema.org type and is deliberately NOT proposed for the picker.
`project_creator_link_policy` gates adult content behind an allowlist and a takedown path; offering it
as a one-click business type invites exactly what that policy exists to control. Revisit with that
policy, not here.

## Open question

**Should the broad bucket be derivable instead of chosen?** Every specific type has exactly one honest
schema.org parent. If the tenant picks `Physiotherapy`, we know the bucket. Asking for both invites the
mismatch that prompted this plan — the author picked `ProfessionalService` for a spa and so never saw
`DaySpa`. A single searchable list of specific types, with the broad bucket derived and the broad types
offered only as "none of these fits", may be the better interface.
