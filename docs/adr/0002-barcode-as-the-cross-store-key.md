# 2. The barcode is the cross-store product key

**Status:** accepted, 2026-09-17

## Context

With one collection per store ([ADR 1](0001-one-collection-per-store.md)),
something has to say that Tesco's listing and Auchan's listing are the same
product. The candidates were a name-and-brand match, an embedding similarity
match, a hand-curated table, or the barcode.

Name matching is unreliable in both directions: the same yoghurt is written
three ways, and two different pack sizes differ by one character. Embedding
similarity is good at "similar" and bad at "identical", which is the opposite
of what a price comparison needs - telling a shopper that a 1 l milk costs less
elsewhere when the cheaper one is 0.5 l is worse than saying nothing. A curated
table does not scale past a few hundred products.

Both shops publish barcodes: Tesco as a zero-padded GTIN-14, Auchan as EAN-8 or
EAN-13.

## Decision

The **normalised barcode** is the product key across stores. `gtin_norm` is the
digits with leading zeros removed, so `00000054026193` and `54026193` compare
equal. A product group is `g:{gtin_norm}`.

**Restricted circulation codes are never grouped.** An EAN-13 beginning with
`2` is assigned by the shop itself, for weighed and in-store-packed goods. Two
shops hand out the same code for unrelated products, so equal codes there mean
nothing. Such offers exist on their own and are marked `is_weighed`.

A barcode shorter than 7 digits is an internal article number, not a barcode,
and is ignored.

## Consequences

- Linking is exact and needs no maintenance: it works the moment both shops
  publish the same barcode, and never links two different products.
- It is deliberately conservative. Products without a barcode, own-brand
  products, and weighed goods appear as single-store rows. About 6,200 of
  ~38,000 products are linked, and that is the honest number, not a shortfall.
- The group is resolved through each store's indexed `gtin_norm` at query time,
  so there is no link table to go stale after a scrape.
- Semantic similarity is still used, but for "similar products", where being
  approximately right is the point.
