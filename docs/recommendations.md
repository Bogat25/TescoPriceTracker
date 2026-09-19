# Recommendations

What the tracker suggests to a visitor, how it decides, and what it deliberately
does not do. The code is `stores/recommendations.py`; the vectors it relies on
are described in [semantic-search.md](semantic-search.md) and the categories it
groups by in [stores.md](stores.md#6-categories).

---

## 1. What it does

Two answers, from one endpoint:

- **Cold start** — for a visitor who is not signed in, or who watches nothing:
  the biggest current discounts across the selected stores.
- **Personal picks** — for a signed-in visitor with alerts: products similar to
  the ones they already watch, in the categories they watch most, weighted
  towards a real saving. Anything left over is filled with discounts.

Both answer in **product rows**: a product several stores sell is one entry
carrying each store's price, cheapest first. A recommendation is about a
product, not about a listing.

---

## 2. The algorithm

```
  alerts of the signed-in user
        |
   [1]  resolve each target to offers in every selected store
        |     g:{gtin}      -> the offer in each store that sells it
        |     auchan:123    -> that store's offer
        |     123           -> a Tesco listing (alerts stored before targets existed)
        v
   [2]  bucket them by the SHARED category vocabulary
        |     tesco  "Alapvető élelmiszerek > Tejtermékek"  -> dairy
        |     auchan "Élelmiszer > Tej, tojás"              -> dairy
        v
   [3]  keep the top 5 categories
        |     primary:   how many distinct products the user watches there
        |     tie-break: the most recent alert in that category
        v
   [4]  share the slots out evenly (3 categories, 100 slots -> 34, 33, 33)
        v
   [5]  per category: mean vector of the watched products in it
        |     -> nearest neighbours across EVERY selected store (6x oversearch)
        |     -> drop hits outside the category, and anything already watched
        v
   [6]  group the hits by barcode, score each row
        |     0.5 x similarity + 0.5 x discount
        v
   [7]  cap one brand's variants, merge the buckets, deduplicate, best first
        v
   [8]  fill any remaining slots with the biggest discounts
```

### Why each step is there

**[1] Resolving to offers, not to one store's products.** The watched product is
whatever the alert points at; its vector may live in any store. Resolving in
every selected store is what lets a pick come from a store other than the one
the alert was created in.

**[2] The shared vocabulary.** Each shop's own category tree is its own. Bucketing
by one store's strings would mean a user's Auchan alerts never met a Tesco
category, and the buckets would fragment. The mapping
([ADR 8](adr/0008-learned-category-mapping.md)) is what makes one bucket hold
both stores' products.

**[3] Top five, by breadth then recency.** Breadth first, because two alerts in a
category say more about a habit than one alert does; recency only breaks ties,
so a burst of recent alerts cannot crowd out a long-standing interest.

**[4] Even slots.** Every kept category is represented. Without this, one large
bucket's high similarity scores would take the whole page and the result would
read as "more of the same".

**[5] Mean vector, and oversearch.** The mean of a user's watched products in a
category is a cheap centroid of that interest. Searching 6x the slots leaves room
for the filters that follow, and - the reason it is not smaller - gives the
discount half of the score some savings to actually promote (section 8).

**[6] Two signals.** Similarity alone recommends near-duplicates of what the user
already has; discount alone is just the cold start. Equal weights keep a pick
both relevant and worth acting on.

**[7] One row per product, and no brand takeover.** The same barcode found in two
stores is one recommendation with two prices, never two entries. At most
`MAX_PER_BRAND` of a bucket's picks share a brand, because the nearest neighbours
of a product are usually the same product in another size.

**[8] Filling.** A short personal list is padded rather than shown half empty. The
response reports `personalized_count`, so a caller can tell the two apart.

---

## 3. What it is not

**It is not collaborative filtering.** Nothing compares one user to another, and
no co-occurrence between products is counted. Every signal comes from the
visitor's own alerts and the product texts.

That is a deliberate limit, not an omission:

- The user base is small. Collaborative filtering needs overlapping histories to
  find neighbours, and with few users every neighbourhood is noise.
- Alerts are sparse and intentional. A visitor has a handful, each a deliberate
  act, so there is far more signal per alert than in implicit clicks.
- A content-based pick can be explained — "similar to something you watch, and
  discounted" — which a matrix factorisation cannot.

If the word **hybrid** is used for this recommender, it must be defined as
*semantic similarity combined with a business signal*. It is not hybrid in the
usual sense of content-based plus collaborative.

---

## 4. Degrading

Every step has a fallback, and the answer is never an error:

| Situation | Answer |
|---|---|
| Not signed in | Cold start |
| Signed in, no alerts | Cold start |
| Alerts, but none of the watched products has a vector yet | Cold start |
| Qdrant or the embedding service is unavailable | Cold start, logged as `recommendations.semantic_unavailable` |
| A watched product is in a category that is not mapped | It buckets under "uncategorised" and still produces picks, without a category filter |
| Fewer picks than requested | The rest is filled with discounts |

`personalized_count` in the response says how many of the rows were personal, so
a degraded answer is visible rather than silent.

---

## 5. The endpoints

| Endpoint | Answers |
|---|---|
| `GET /api/prices/recommended/cold?stores=&limit=` | Cold start: the biggest discounts across the selected stores |
| `GET /api/prices/recommended/personalized?stores=&limit=` | Personal picks, then discounts. Needs a Bearer token; 401 without one |
| `GET /api/prices/recommendations/*` | **Legacy, Tesco only.** The original engine in `backend-api/recommendation_engine.py`; 404 while Tesco is disabled |

Response shape:

```json
{
  "type": "personalized",
  "personalized_count": 7,
  "stores": ["tesco", "auchan"],
  "results": [ { "group_id": "g:5998200557001", "name": "...", "best_price": 379.0,
                 "cheapest_stores": ["auchan"], "store_count": 2, "offers": [ ... ] } ]
}
```

---

## 6. Tuning

The constants are at the top of `stores/recommendations.py`:

| Constant | Value | Effect of raising it |
|---|---|---|
| `TOP_CATEGORIES` | 5 | More of the user's interests represented, fewer slots each |
| `OVERSEARCH` | 6.0 | More savings in the pool to promote, more Qdrant work per request |
| `MAX_PER_BRAND` | 3 | More of one brand's variants allowed in a bucket |
| `SIMILARITY_WEIGHT` | 0.5 | More "like what I watch", less "worth buying" |

`OVERSEARCH` and `MAX_PER_BRAND` were set from the measurement in section 8;
the other two are reasoned, not calibrated. `scripts/recommendation_eval.py`
takes `--oversearch` and `--max-per-brand`, so a change can be measured against
the current setting before it is adopted.

---

## 7. Operations

Personal picks need vectors, so they follow the vectorizer: a product that has
not been embedded yet can neither be a source nor a pick. A full index of
~38,000 products takes 4–8 minutes and runs after each scrape.

What to look for when recommendations seem wrong:

- `recommendations.semantic_unavailable` in the logs — the picks are discounts
  because Qdrant or the embedding service was unreachable.
- `type: "cold_start"` for a user who has alerts — their watched products have
  no vectors, or none of their categories mapped.
- Picks that ignore a store — check that the store is enabled and that its
  products are embedded.

---

## 8. What it measures (2026-09-19)

`scripts/recommendation_eval.py`, 40 synthetic seeds of one watched product
each, 24 recommendations, against the live catalogue:

| Measure | Value | Reading |
|---|---|---|
| Seeds that produced picks | 37/40 | The path works for most products |
| Picks in the seed's category | 0.973 | Topically accurate |
| Overlap with the discount-only list | 0.005 | Personalisation is doing something distinct |
| Mean discount of picks | 0.026 | **Barely above the catalogue's 0.024** |
| Intra-list diversity | 0.096 | **Picks were near-identical to each other** |
| Distinct products reachable | 668 | **1.8 % of the catalogue** |
| Picks from another store | 0.056 | Low, but only 6,228 products are linked at all |
| Median latency | 0.01 s | |

Leave-one-out over the 12 users who watch more than one product, hiding each
one's newest alert:

| | Content-based | Discount-only baseline |
|---|---|---|
| Hit rate @24 | **0.250** | 0.000 |
| MRR | 0.091 | — |

The recommender predicts a user's next alert a quarter of the time; the
discount list never does. Twelve users is far too few to be conclusive, and it
is reported as indicative.

**What the measurement changed.** The three poor numbers share one cause: the
candidate pool was 2.5 slots wide, a tight neighbourhood of near-identical
products that rarely contains a saving — about two discounted candidates in
sixty, which is exactly the 0.026 mean. `OVERSEARCH` went to 6.0 so the score
has savings to promote, and `MAX_PER_BRAND` caps one brand's variants, which is
what made the picks near-identical. Both are measurable again with the same
script.

**What the measurement did not change.** The scoring is still
`0.5 x similarity + 0.5 x discount`. Rank fusion was tried, on the theory that a
cosine and a ratio are not comparable, and rejected: the arithmetic shows the
weighted sum already gives a discount a 0.25 spread against similarity's 0.055,
so the saving was never being drowned out, and fusing by rank would have let a
barely relevant product outrank a close match for being the only one on offer.
The search fuses two *relevance* signals, where equal footing is right; here one
signal is relevance and the other is desirability, and they are not equals.

---

## 9. Limitations, and what would improve it

1. **Thinly evaluated.** Section 8 measures the shape of the results and a
   leave-one-out hit rate over twelve users. There is still no click-through
   data, so nothing measures whether a recommendation was *wanted* rather than
   merely predictable. Logged impressions would fix that, with "an alert created
   on a recommended product" as the success signal.
2. **Alerts are the only signal.** Views, searches and comparisons are not used,
   so a visitor who browses heavily but alerts on nothing gets a cold start.
3. **The centroid flattens taste.** One mean vector per category treats a user
   who watches milk and cheese as watching their average. Clustering within a
   category would separate them.
4. **Discount is a blunt instrument.** `discount_ratio` treats 20 % off a
   staple and 20 % off a luxury item as equal, and a price that rose before the
   promotion is not detected.
5. **Cold start ignores the visitor entirely.** Popularity, seasonality and the
   current basket are all unused.
6. **No diversity guarantee beyond categories.** Within a bucket, five variants
   of the same product can fill the slots.
