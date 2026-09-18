# 9. Recommendations are content-based, and about products rather than listings

**Status:** accepted, 2026-09-18

## Context

The personal recommender was built when Tesco was the only store, and it stayed
that way after Auchan arrived: candidates came from the Tesco collection, the
whole path was skipped while Tesco was disabled, and the buckets used Tesco's
own category strings from the vector payload. Another store's prices were
attached to a pick afterwards by barcode, so a visitor saw both stores but could
never be recommended a product only the other store sold.

In a system whose premise is that no store is special, this was the one place
the premise did not hold. Two questions had to be answered to fix it.

**What groups a user's interests, now that two stores have different category
trees?** The shared vocabulary from [ADR 8](0008-learned-category-mapping.md)
did not exist when the recommender was written.

**What is a recommendation about?** A product several stores sell could occupy
one slot carrying both prices, or compete for a slot per store.

## Decision

**Products, not listings.** A barcode group is one pick, showing each selected
store's price. A page of ten recommendations is ten products.

**Bucket by the shared categories.** The watched products are resolved to offers
in every selected store and grouped by the canonical category, so one bucket
holds both stores' products. Vector hits are filtered back to the bucket's
category through the same mapping, because a point's own payload category is its
store's.

**Content-based, deliberately.** Picks come from the visitor's own alerts and
the product texts. No collaborative signal is used: the user base is too small
for neighbourhoods to be anything but noise, and a content-based pick can be
explained to the person receiving it.

**Two signals, equally weighted.** `0.5 x similarity + 0.5 x discount`, so a
pick has to be both relevant and worth acting on.

## Consequences

- A product only one store sells can be recommended, which was impossible
  before. Picks work with any store selection, including one without Tesco.
- A shopper comparing prices sees one row per product rather than the same
  yoghurt three times, which matches every other listing in the product.
- Deduplicating by barcode means unlinkable products - no barcode, own brand,
  weighed goods - compete as single-store rows. That is the same trade-off the
  whole catalogue makes ([ADR 2](0002-barcode-as-the-cross-store-key.md)).
- Calling this a "hybrid" recommender requires defining the term as *similarity
  plus a business signal*. It is not content-based plus collaborative, and a
  reader who assumes the usual meaning will look for a component that is not
  there.
- The weights and the bucket count are reasoned, not measured. There is no
  offline evaluation, and adding one needs logged impressions and a definition
  of success - see [recommendations.md](../recommendations.md) section 8.
- The legacy `/api/v1/recommendations/*` endpoints keep the original Tesco-only
  engine. They are Tesco-only by definition, so making them store-neutral would
  change what they mean rather than improve them.
