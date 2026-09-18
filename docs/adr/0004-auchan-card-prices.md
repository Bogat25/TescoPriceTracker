# 4. Auchan card prices: accept partial coverage and label it

**Status:** accepted, 2026-09-17 (decision D3)

## Context

Tesco publishes its Clubcard price for every product, so the `loyalty` channel
is complete there. Auchan does not: an anonymous response carries the card
price only as a discounted **unit** price, and only for the ~380 products
flagged as having a card offer. GVH Arfigyelo shows card prices for perhaps
1,250 more, which appear to sit in a category that is empty for anonymous
visitors.

The options were: (a) accept the partial coverage and label it, (b) build a
logged-in reader using a loyalty account, or (c) drop the loyalty channel for
Auchan entirely.

A throwaway loyalty account was created to test (b), and it would work.

## Decision

**(a)** Accept partial coverage and say so in the product where it matters. The
comparison page states that card prices are known for part of Auchan's range.
The logged-in reader is not built.

Where the card price is known, the shelf price is reconstructed from the card
unit price: multiplying the unit price by the pack size is rounded to whole
forints, so the reconstruction chooses between that and the whole discount
percentage, whichever has the smaller error bound.

## Consequences

- The `loyalty` channel means the same thing in both stores - the best price a
  card holder gets - but is complete for Tesco and partial for Auchan.
- Comparisons therefore report **regular prices and best prices separately**, so
  a reader is never shown a comparison whose two sides know different amounts.
- Rejected (b) because it would put a personal account's credentials in the
  stack, Auchan's terms are not clearly permissive about it, and card prices may
  depend on the account's loyalty level - the data would be one account's view
  presented as everyone's.
- If Auchan starts publishing card prices anonymously, only the mapper changes.
