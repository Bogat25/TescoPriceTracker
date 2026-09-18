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
        |     -> nearest neighbours across EVERY selected store (2.5x oversearch)
        |     -> drop hits outside the category, and anything already watched
        v
   [6]  group the hits by barcode, score each row
        |     0.5 x similarity + 0.5 x discount
        v
   [7]  merge the buckets, deduplicate by product, best score first
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
category is a cheap centroid of that interest. Searching 2.5x the slots leaves
room for the filters that follow, so a bucket rarely comes back short.

**[6] Two signals.** Similarity alone recommends near-duplicates of what the user
already has; discount alone is just the cold start. Equal weights keep a pick
both relevant and worth acting on.

**[7] One row per product.** The same barcode found in two stores is one
recommendation with two prices, never two entries.

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
| `OVERSEARCH` | 2.5 | Fewer short buckets after filtering, more Qdrant work per request |
| `SIMILARITY_WEIGHT` | 0.5 | More "like what I watch", less "worth buying" |

None of them is calibrated against a measured target — unlike the search
threshold, which was ([search-eval.md](search-eval.md)). They are defensible
defaults, and section 8 says what measuring them would take.

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

## 8. Limitations, and what would improve it

1. **Not evaluated.** There is no offline measurement of recommendation quality,
   no held-out set and no click-through data. The weights are reasoned, not
   measured. An honest evaluation would need logged impressions and a decision
   about what counts as success — an alert created on a recommended product is
   the obvious candidate.
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
