# 8. The cross-store category mapping is learned, not configured

**Status:** accepted, 2026-09-18

## Context

Category filters disappeared when the catalogue became store-neutral, because
each shop has its own tree and the two do not correspond. Tesco has
super department, department, aisle and shelf; Auchan has a path of variable
depth with different names and different boundaries.

Three ways to get one vocabulary: maintain a mapping table by hand; ask an
embedding model which Tesco category a product belongs to; or derive the
mapping from the products both shops already sell.

A hand-maintained table goes stale silently, and neither shop announces a tree
change. An embedding classifier would have to be evaluated, would need the
embedding service to be up to filter a catalogue page, and would be wrong in
ways nobody could explain to a user.

The third option had something the others did not: **6,228 products already
linked by barcode**, each of which is a labelled example that costs nothing.

## Decision

Tesco's two top levels are the canonical vocabulary - it is the larger
catalogue and the site has always browsed by it. Another store's paths are
mapped onto it by counting, over the linked products, how often a source path
coincides with a canonical category. Votes are accumulated at **every prefix**
of the source path, and a path takes the **deepest prefix** that clears both
thresholds: at least **3** linked products, and at least **60 %** agreement.

A path that clears neither is **left unmapped**, not guessed. The build reports
how many paths and how many products each store's mapping covers.

The mapping is derived data in `category_map`, rebuilt in the same step that
rebuilds the statistics after a scrape.

## Consequences

- A new store needs no category configuration: give it `iter_categories()` and
  enough shared products and its tree maps itself.
- It cannot invent a category a shop does not stock, and it says so - a store
  with nothing in a category is a filter that matches nothing, which is a
  different answer from "no filter".
- Coverage depends on overlap. A store that shares few products with Tesco maps
  little; the coverage figures make that visible rather than hiding it behind
  a plausible-looking guess.
- Deep niche leaves still map, through their parent, which is what the prefix
  roll-up is for. A leaf mapped at depth 1 is coarser than one mapped at depth
  3, and the stored entry records which depth was used.
- The filter exists twice: an indexed Mongo fragment for text and browse
  queries, and a Python predicate for vector hits, which carry no category of
  their own. A test asserts the two select the same products.
- Auchan's own category ids are not used. They would be a second identifier to
  keep in step for no gain, since the mapping is keyed by the path the offer
  already carries.
