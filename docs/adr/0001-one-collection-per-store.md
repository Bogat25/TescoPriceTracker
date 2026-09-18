# 1. One collection per store, with a shared offer layer

**Status:** accepted, 2026-09-17

## Context

The tracker held one MongoDB collection, `products`, shaped exactly like
Tesco's API: `tpnc` as the key, `clubcard` prices, a four-level department
tree. Adding Auchan meant either forcing Auchan into that shape, migrating
everything into a new neutral shape, or giving each store its own collection.

Auchan's documents genuinely differ: a different product id, EAN instead of
GTIN-14, a category path of variable depth, loose goods priced per kilo, and a
loyalty price published only as a unit price. A common shape wide enough for
both would have been the union of two vocabularies, and every later store would
have widened it again.

A migration was also a risk out of proportion to the gain: the Tesco collection
already carried months of daily price history that nothing may lose.

## Decision

Each store keeps **its own collection in its own shape**. Shared code never
reads a store collection directly; it goes through a per-store **adapter** that
maps documents to one neutral **offer** shape. Joins across stores happen in
the query layer, not in the database.

The Tesco collection is not migrated. Its `clubcard` becomes `loyalty` when it
is read, not when it is stored.

## Consequences

- A store can be added without touching any other store's data, and removed by
  dropping a collection and a registry row.
- Nothing above `stores/<store>/` knows a store-specific field name, which is
  what makes the rest of the system store-neutral.
- Cross-store queries cost more than a single indexed query would: each store
  is queried separately and the results merged in Python. The result window is
  capped (`skip + limit <= 1000`) so a deep page cannot load unbounded data.
- A count across stores is a sum of per-store counts, so `total` counts offers,
  not product rows. The API says so with `total_counts_offers`.
- The linking that a single shared collection would have given for free has to
  be done explicitly - see [ADR 2](0002-barcode-as-the-cross-store-key.md).
