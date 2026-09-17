# Store spike: PENNY Hungary (penny.hu)

Status: **investigated 2026-09-16**, candidate for the second store in
[upgrade-plan.md](upgrade-plan.md) Phase 2 (step 4.0).

**Verdict:** technically the easiest possible source. The data is a
**weekly-offer catalogue**, not a full shop range, so the data model and the
comparison features must be designed around validity windows.

---

## 1. How it was found

`https://www.penny.hu/termekek%2Ffriss-hus` is a server-side rendered Nuxt app.
The page's `__NUXT_DATA__` payload contains a key
`product-group-friss-husok-felvagottak-3474-{"page":0,"pageSize":50}`, and the
main bundle (`/_nuxt/*.js`) calls a REST API under `/api/product-discovery/`.
The backend behind it is **commercetools** (project `penny_hu_prod`), the same
REWE Group platform as the other PENNY countries.

## 2. Endpoints (tested)

No API key, no cookies, no CSRF token, CORS `*`. All `GET`, JSON.

| Endpoint | Result |
|---|---|
| `/api/product-discovery/products?page=0&pageSize=500` | **Whole catalogue**, `{count, offset, total, results, facets}`; `total` was 1026 |
| `/api/product-discovery/categories/tree` | Category tree (offer weeks + 15 product categories) |
| `/api/product-discovery/categories/{slug}/products?page=&pageSize=` | Products in a category; needs the **slug** (`friss-husok-felvagottak-3474`), not the key (`3474` → 404) |
| `/api/product-discovery/products/{sku}` | Product detail by SKU (`86-100020`); adds `countryOfOrigin`, `nutIngredients`, `storageType`, `features`, meat origin, wine fields, … (mostly empty strings) |
| `/api/product-discovery/products/search/{query}` | Text search (`search/tej` → 5 results) |
| `/api/stores` | All stores with address, coordinates, features |
| `/api/product-discovery/products/{slug}/similar` | Exists; takes the slug, not the SKU |

Try in a browser:

- https://www.penny.hu/api/product-discovery/products?page=0&pageSize=50
- https://www.penny.hu/api/product-discovery/categories/friss-husok-felvagottak-3474/products?page=0&pageSize=50
- https://www.penny.hu/api/product-discovery/products/86-100027
- https://www.penny.hu/api/product-discovery/categories/tree

Limits and behaviour observed:

- `pageSize` max **500** (commercetools `limit` range 0..500; above that the API
  returns 400 and exposes internal request details; do not send it).
- Full catalogue = **3 requests**, ~0.3–1.0 s each.
- 30 sequential requests: all 200, avg 0.27 s, no rate-limit headers,
  `Cache-Control: no-store`.
- A `python-requests` User-Agent is accepted as well.
- `robots.txt` contains only a `Sitemap:` line, no `Disallow` rules.
- Still: scrape once a day, sequentially, with a descriptive User-Agent and a
  pause between requests. The terms of use have not been reviewed yet; do that
  before production use.

## 3. Product record

```json
{
  "sku": "86-100027",
  "productId": "…uuid…",
  "slug": "karat-mester-sonka-86100027",
  "name": "KARÁT MESTER SONKA",
  "category": "Friss húsok, felvágottak",
  "parentCategories": [[{"key": "3474", "slug": "friss-husok-felvagottak-3474", "name": "…"}],
                       [{"key": "99009342", "name": "Ajánlatok 09.17-09.23. között"}, …]],
  "amount": "100", "volumeLabelShort": "g", "packageLabel": "darab",
  "weightArticle": false,
  "images": ["https://images.cdn.europe-west1.gcp.commercetools.com/…jpg"],
  "price": {
    "regular":  {"value": 39900, "perStandardizedQuantity": 399000, "tags": ["SO"]},
    "crossed": 59900,
    "discountPercentage": -33,
    "lowestPrice": 39900,
    "baseUnitShort": "KG",
    "validityStart": "2026-09-24",
    "validityEnd": "2026-09-27"
  }
}
```

Price fields (all amounts in **fillér**, divide by 100 for Ft):

| Field | Seen on | Meaning | Maps to our channel |
|---|---|---|---|
| `regular.value` | 1026/1026 | Price you pay in the offer window | `normal`, or `discount` when `crossed` exists |
| `regular.perStandardizedQuantity` | all | Unit price per `baseUnitShort` (KG / lt / db) | `unit_price` |
| `crossed` + `discountPercentage` | 355 | Crossed-out previous price | `normal` = `crossed`, `discount` = `regular` |
| `loyalty.value` | 126 | PENNY card price | `loyalty` (Tesco: `clubcard`) |
| `standard.value` | 80 | Standard price next to a `pt-aktion` promo | `normal` |
| `lowestPrice` | 297 | Probably the 30-day lowest price shown for EU price-reduction rules (not confirmed) | extra field |
| `regular.tags` | – | `IO`, `SO`, `pt-aktion`, `pt-multi`, `pt-familie`: meaning not confirmed | store raw |
| `validityStart` / `validityEnd` | all | Offer window; `2049-12-31` = permanent | **new: required** |

There is **no GTIN/EAN** and **no separate brand field**; the brand is the
start of the upper-case `name`.

## 4. What the data actually is

- The site is PENNY's **online leaflet**, not a full online shop.
  Of 1026 products only **92** are permanent (`2049-12-31`); the rest are
  offers grouped into **three weeks at once**: the current, the next and the
  one after (e.g. `09.10–09.16`, `09.17–09.23`, `09.24–09.30`).
- **Future prices are published in advance.** A product valid from
  `2026-09-24` is already in the feed on `2026-09-16`.
- No SKU appeared in two offer weeks in this snapshot. Most products have one
  SKU; 11 name+size pairs have several SKUs (flavour/pack variants, and at
  least one possible re-listing: `SISSY TEJ 1 l` as `86-20149` in week 1 and
  `86-2084` in week 3). Whether a product keeps its SKU across later offer
  weeks is **unknown**; see step 5.3.
- Products most likely disappear from the feed after their window ends, so
  history exists only for periods when a product is advertised.
- Prices are national (the site has no store-level prices;
  `featureProductStoreAvailability` is off).

## 5. Consequences for the design

1. **Adapter is trivial**: 3 paged calls a day instead of Tesco's sitemap +
   one GraphQL call per product. No API key to manage in SecretManager.
2. **Store offers, not daily prices.** Save each observation as
   `{store, sku, price fields, validityStart, validityEnd, first_seen, last_seen}`.
   A daily `price_history` entry for a day is derived only when that day falls
   inside a window. Never record a future window as today's price.
   This also gives a feature Tesco lacks: "upcoming price drops".
3. **Watch SKU stability before building history on it.** Take a daily snapshot
   for 2–3 weeks (as the offer weeks roll over) and check whether the same
   product returns under the same SKU. If not, the product identity must be
   `normalised name + amount + unit`, with the SKU kept only per offer.
4. **Matching with Tesco needs the embedding approach.** A naive test searched
   40 random branded, non-own-label Penny products by their first three words in
   the Tesco tracker API:
   - brand found at Tesco: **31/40**,
   - same product *and* size, checked by eye: **about 8/40** (e.g. Marlenka
     mézes golyó 235 g, Paloma őrölt kávé 225 g, Nescafé Cappuccino 108 g,
     Pur Aloe Vera 1200 ml, Hey-Ho Piros 1 l, Zott Jogobella 150 g),
   - the rest were the same brand with a different flavour or pack size.
   Without GTIN, matching must combine embeddings, brand extracted from the
   name, and normalised size (`amount` + `volumeLabelShort` vs Tesco
   `pack_size_value` + `pack_size_unit`).
   The sample was random from one snapshot, so treat these numbers as indicative.
5. **Own labels** (`PENNY`, `SAN FABIO`, `KARÁT`, `SISSY`, `DÁRDÁS`, `MÁRKA`, …)
   will not match Tesco products; use them for category-level comparisons
   (e.g. price per kg of ham) instead.
6. **Statistics** built on continuous daily history (volatility, price index)
   need per-store handling: Penny's series have gaps between offers.
7. **Categories**: the 15 permanent categories (`…-3474` etc.) map to our
   super-department level; offer-week categories are promotion groupings and
   should be stored as tags, not as the product's category.

## 6. Can penny.hu give the full range every day? No.

Checked 2026-09-16:

- `sitemap.xml` lists **1027** `/products/…` pages, the same set as the API
  feed (1026). Nothing is hidden from the listing.
- `products/{sku}` for 30 SKUs next to known ones (not in the feed): all 404.
- `products/search/{q}` only returns products that are already in the feed
  (`kávé`: 15 results, 0 outside it).
- The frontend only passes `page`, `pageSize`, `skus` and a category filter;
  there is no parameter for unpriced or non-promoted products. The backend
  query itself filters `variants.price.centAmount: range (1 to *)`.

PENNY Hungary has no online shop, so it publishes no everyday prices for
products that are not in the leaflet. A Tesco-like full daily catalogue only
exists for chains that **sell online** (candidates to check: Auchan, SPAR,
Kifli.hu).

## 7. Alternative source: GVH Nemzeti Árfigyelő (arfigyelo.gvh.hu)

Under Government Decree 163/2023 and the Árfigyelő act, large retailers must
report **daily prices** (normal, discounted, loyalty) for products in defined
basic categories. The GVH site is a Vue app backed by an anonymous JSON API.

| Endpoint (`https://arfigyelo.gvh.hu/api`) | Result |
|---|---|
| `/chain-stores` | 9 chains: Spar, Rossmann, Penny, dm, Aldi, Tesco, Müller, Auchan, Lidl |
| `/shops` | 1824 stores with chain, address, coordinates |
| `/categories` | 9 top-level → 161 leaf categories (e.g. "Pasztőrözött ESL tej, 2,8%") |
| `/products-by-category/{leafId}?limit=500&offset=0` | Products with prices from every chain; `count` for paging. **Default page size is 12**, so always pass `limit` |
| `/product/{id}` | Detail: per-chain prices, `pricesMax`, `priceSameEverywhere`, `availableInShops` (store IDs) |
| `/search` | Exists; parameter name not identified (wrong guesses return 500; stop guessing) |

Full crawl on 2026-09-16: 161 requests with `limit=500`, 0.4 s pause, 89 s,
no errors.

| | Value |
|---|---|
| Products | **5314**, of which **4276 keyed by GTIN**; the rest `{chain}-{internal id}` |
| Products per chain | Auchan 1539, Tesco 1027, Spar 1006, Rossmann 872, Müller 658, dm 524, Lidl 416, Aldi 409, **Penny 346** |
| Price types | `NORMAL` for every entry; `DISCOUNTED` and `LOYALTY` where active |
| Same GTIN at 2+ chains | 965 products (no product showed more than 3 chains; not yet known whether that is a cap) |
| Shared with Tesco | Auchan 329, Spar 204, Lidl 17, Penny 12 |
| Not covered | Anything outside the defined categories, e.g. **no Coca-Cola** at all |

Penny in Árfigyelő:

- 346 products, **every day, including non-promoted ones** (dairy 102, meat 61,
  pantry/drinks 56, fruit/veg 37, hygiene 32, …).
- 277 use IDs like `penny-20149`, which is the penny.hu SKU `86-20149`
  (Sissy UHT tej 2,8%: Árfigyelő `NORMAL 315` / `DISCOUNTED 225`, penny.hu
  `crossed 31500` / `regular 22500`). 75 of the 277 are in today's penny.hu
  feed. **The two sources can be joined on this ID.**

Terms (visitor terms, in force from 2025-07-20):

- No clause about automated access or bulk download.
- XIV.2: trademarks and protected content shown on the site may only be used
  for the site's purpose (informing consumers); other uses need the rights
  holder's consent.
- XII.7: GVH accepts no liability for the accuracy of the data.
- For a thesis project, email `arfigyelo@gvh.hu` to describe the use and ask
  whether an official data export exists. Do not re-host product images; link
  them or use the stores' own images.

### 7.1 Linking Árfigyelő products to individual products

ID formats per chain (crawl of 2026-09-16):

| Chain | GTIN-keyed | Own ID | Own ID example |
|---|---|---|---|
| Tesco | **1027** | 0 | – |
| Auchan | 1539 | 0 | – |
| Spar | 944 | 62 | `spar-484054001` |
| Rossmann / dm / Müller | 872 / 524 / 658 | 0 | – |
| Aldi | 46 | 363 | `aldi-320542` |
| Lidl | 80 | 336 | `lidl-0001587` |
| Penny | 69 | 277 | `penny-21240` |

Linking rules, strongest first:

1. **Tesco tracker ↔ Árfigyelő: exact GTIN.** The scraper already stores
   `gtin` on each product. A sample of 21 Árfigyelő Tesco GTINs found through
   the tracker's name search: **13 matched exactly**, and in every match the
   Árfigyelő price equalled the price the tracker scraped that day (e.g.
   `5051007159432` Tesco porcukor 500 g = tpnc `220157825`, 289 Ft both). The 8
   misses were name-search failures on abbreviated names (`TS HANTOLT VOROS
   LENCSE 500G`), not missing GTINs. In the system, join on an indexed
   `products.gtin` field instead of searching.
   - Normalise GTINs before joining: digits only, strip leading zeros for
     comparison (`0000080418900` vs `80418900`; dm uses 8-digit EAN-8).
   - Codes starting with `2` and ending in zeros (`2802590000000`, "Ft/kg")
     are in-store weighed items. They matched Tesco, but they are chain-internal
     and must never be used for cross-chain matching.
   - Coverage: about 1027 of the tracker's ~22k Tesco products.
2. **Same product at other chains: already merged by Árfigyelő.** One
   GTIN-keyed product entry lists every chain that reports it (965 products
   at 2+ chains), so branded-product comparison needs no matching.
3. **Own-label products (`aldi-N`, `lidl-N`, `penny-N`, `spar-N`): compare by
   leaf category.** They have no cross-chain identity, but Árfigyelő's 161
   leaf categories are like-for-like groups ("Pasztőrözött ESL tej, 2,8%") with
   `unitAmount`. Compare the cheapest unit price per chain per leaf category.
4. **Penny extras:** `penny-{n}` = penny.hu SKU `86-{n}` adds images, unit
   prices and promotion windows.
5. **Everything else** (Tesco products outside Árfigyelő, Árfigyelő products
   without GTIN): embedding + brand + normalised size matching. Use the GTIN
   matches from rule 1–2 as the labelled set to measure its precision and
   recall.

Notes on prices:

- `priceSameEverywhere: false` for 352 Tesco entries (also some Spar, Auchan,
  Lidl): the price differs by store. The list shows `productMinAmount`; the
  detail has `pricesMax`. The law defines the daily price as the one applied in
  80% of a chain's stores.
- Árfigyelő is only a daily snapshot. History has to be built by storing a
  snapshot every day, like the Tesco scraper does.

### 7.2 Coverage against the Tesco range

| | Products (2026-09-16) |
|---|---|
| Tesco online range (sitemap) | 19,317 |
| Tracker, active today | 19,311 |
| Tesco products in Árfigyelő | 1,027 (~5%) |

Árfigyelő is a comparison layer for basic products, not a full-range source.

## 7.3 Other sources for Penny's full range

| Source | Result |
|---|---|
| **foodora.hu** (Penny's delivery partner since Nov 2024, "2000+ products", store-level shops such as `/shop/ygwq/penny-regi-foti-ut`) | The only place with the full range online. The server-rendered page has only the category tree (123 categories). Products load through foodora's groceries GraphQL (`GetGroceryProducts`, fields `price`, `originalPrice`, `sku`, `globalCatalogID`, `stockAmount`). The public `hu.fd-api.com/api/v5/graphql` does not expose the groceries schema (introspection disabled). A headless Chrome session was blocked by **PerimeterX** bot protection ("Access to this page has been denied"). **Not usable without permission**: getting around it would mean defeating their bot protection. |
| Wolt | No evidence that Penny is on Wolt in Hungary. |
| PENNY mobile app (`hu.penny.app`) | Leaflet, PENNY card and coupons; not inspected, most likely the same backend as penny.hu. |
| Árnéni (arneni.com) and leaflet sites | Built on GVH Árfigyelő plus leaflet offers; no extra source. |

Conclusion: no open source exists for Penny's full daily range. The options
are (a) penny.hu leaflet + Árfigyelő (~1,300 distinct Penny products),
(b) ask foodora / Delivery Hero or PENNY for data access, or (c) choose a
second chain that runs its own online shop.

## 7.4 Hungarian chains with home delivery (2026-09-16, APIs not checked)

| Chain | Delivery channel | Public catalogue with prices | Size signal |
|---|---|---|---|
| Tesco | Own shop (Tesco Otthonról) | Yes | 19,317 product URLs in sitemap |
| **Auchan** | Own shop (auchan.hu/shop) + foodora (all 24 stores) | **Yes**: `/shop` and product pages render prices without login; product pages carry `"price"` and `"sku"` | **50,784** product URLs in sitemap |
| Kifli.hu | Own online-only shop (Budapest area) | Not checked | 15,358 product URLs in sitemap. `robots.txt` **disallows AI agents** (ClaudeBot, GPTBot, …) and several crawlers; not accessed further |
| Coop | Own shop (cooponline.hu, nationwide, mainly shelf-stable) | Partly: homepage shows prices; sampled product URLs redirected to the homepage | 14,533 product URLs in sitemap (WooCommerce) |
| ALDI | Own "ALDI Online" run by ROKSH personal shoppers, 107 settlements | Unknown: `roksh.com/aldi` is a JS app shell; `aldi.hu/hu/online.html` returned 403 | ~3,300 products (press) |
| SPAR / INTERSPAR | **Wolt only** since 2025-03-21 (own shop closed), 40 settlements | Wolt venue pages render items with prices publicly | ~10,000 products (press); 24 Budapest venues on Wolt |
| PENNY | foodora only | No: PerimeterX blocks automated access | 2000+ products (press) |
| Príma / CBA | Wolt ("Príma Expressz", Budapest) | Wolt venue pages | Unknown |
| Lidl | **No delivery** | – | – |

Candidates for a Tesco-like second store: **Auchan** first (own shop, public
prices, largest catalogue, also on foodora), then Coop. SPAR is only
reachable through Wolt.

## 7.5 Lidl (2026-09-16)

- No official online shop and no delivery (a third party, Avokado, delivered
  from Lidl stores in 2024 without any cooperation).
- `lidl.hu` sitemap: **2,049** product pages (`/p/{slug}/p{id}`), food and non-food.
- Product pages carry schema.org `Product` data with `sku`, no GTIN.
- A random sample of 30 pages: about 19 showed a price. Prices appear mainly
  while a product is advertised.
- Árfigyelő: 416 Lidl products with daily prices.
- Verdict: like Penny, partial data only.

## 7.6 Auchan as the second store (API checked 2026-09-16)

### Access

| Step | Detail |
|---|---|
| Frontend | Nuxt; runtime config `auchanApiBrowserHostShop=https://auchan.hu`, `auchanApiPrefix=/api/v2` |
| Token | `POST https://auchan.hu/fe-api/get-token` `{"grant_type":"anonymous"}` → `Bearer` token, `expires_in` 86400. This is the token every anonymous visitor gets. Without it the API returns 401 |
| Category tree | `GET /api/v2/tree/0?depth=1` → root `productCount` 36,247, 23 top-level categories with counts |
| Product list | `GET /api/v2/products?page=N&itemsPerPage=100&isCached=true&categories={categoryId}`; `itemsPerPage` above 100 → 400 (`items_per_page_is_too_large`). `category_id` is ignored; `categoryId` → 404 |
| Segment | `GET /api/v2/cache-segmentation` → `{"cacheSegmentationCode":"SS","companyNo":"SS"}` for anonymous visitors; the frontend keys caches by this code and the postcode, so assortment or price may differ per delivery area (not tested) |
| Product detail | `/api/v2/products/{productId}/variants/{variantId}/details`, `…/details/nutrition`, `…/ingredients`, `…/stock_infos` |
| robots.txt | Allows everything except `/cgi-bin/` |
| Terms | Online shop ÁSZF (2022-04-06 PDF): no clause on automated access or copying content |

### Product record (list endpoint)

`id`, `brandName`, `categoryName`, `isNonFood`, `adultsOnly`,
`selectedVariant.{id, name, sku, eanCode, unit, price.{gross, grossDiscounted,
discountPercentage, isDiscounted}, packageInfo.{packageUnit, packageSize,
unitPrice}, cartInfo.availability, loose.{loose, weightPerPiece},
media.mainImage, isLoyaltyPriceValid, flags}`.

### Full crawl of the grocery categories

Categories: Friss élelmiszer, Fagyasztott, Tartós élelmiszer, Italok, Tudatos
táplálkozás, Szépség/egészség/baba, Állateledel, Otthon/háztartás.
Sequential, 100 per page, 1 s pause: **473 s, 0 errors**.

| Metric | Value |
|---|---|
| Unique products | **15,031** |
| With EAN | **15,031 (100%)**, all unique |
| Available online | 14,363 (667 `notAvailableOnline`) |
| Discounted | 573 |
| Tesco branded GTINs (from Árfigyelő, 774) found in Auchan | **322 (42%)**; Árfigyelő itself listed Auchan for 329, so it is not hiding Auchan listings |
| Auchan online price = Árfigyelő Auchan price (729 GTINs) | 656 same (90%), 73 different. Differences include per-kg vs per-pack cheese prices and several online prices ~100 Ft higher than the reported in-store price |

### Verdict

Auchan fits as the second store: an anonymous, stable JSON API, a full
grocery catalogue comparable in size to Tesco (15k vs 19k), **EAN on every
product** (so matching Tesco on barcode is exact), unit prices, discounts and
availability, and a whole-catalogue crawl in about 8 minutes.

Still to check before building the adapter:

1. Exact Tesco ↔ Auchan overlap: join all Tesco `gtin` values in Mongo with the
   Auchan EAN set (the 42% above only covers basic-category branded products).
2. Whether price or assortment changes by postcode / `companyNo`, and which
   segment to track.
3. Online vs in-store price: document that tracked prices are **online**
   prices (Tesco's are too).
4. Loyalty (Bizalomkártya) prices: `isLoyaltyPriceValid` was false everywhere
   for anonymous visitors.
5. Stability over a few days (token lifetime, SKU/EAN stability, response
   time; one unfiltered 100-item page took 10–13 s, filtered pages ~1–3 s).

### 7.7 Pre-implementation checks (2026-09-17)

| # | Check | Result |
|---|---|---|
| 1 | **Tesco ↔ Auchan overlap, full range** | Random sample of 400 Tesco sitemap products, `gtin` read from the tracker API: **124/400 = 31% (±5)** found in the Auchan grocery crawl, ≈6,000 products. Branded (not own-brand, not weighed): 124/345 = 36%. Own-brand: 0/46. Tesco "Otthon-hobbi" matched 1/71 only because Auchan non-food was not crawled; groceries without it ≈45%. Matched names were identical. On matched products Tesco was cheaper 62×, Auchan 34×, same 28× |
| 2 | **Delivery area** | Area types: `department_store` (pickup) and `public_area`; `POST /api/v2/delivery-area {type, areaId}`. 7 pickup points, all around Budapest. Segments seen: `SS` (default, Soroksár, Törökbálint) and `BK` (Budakalász). ~300 shared products: identical price and availability; category counts 15,915 vs 15,913. **One national online catalogue; track the anonymous default** |
| 3 | **Online vs in-store / deposit** | 90% of Auchan online prices equal Auchan's Árfigyelő (in-store) price. Same basis as Tesco: Coca-Cola 300 ml (EAN 54026193) 295 Ft at both. Tracked prices are online shelf prices for both stores |
| 4 | **Loyalty prices** | Only for logged-in card holders (`/loyalty_card/current`); category 14288 returns 0 items anonymously. Flag `Bizalomkártyás` marks 613 products. Árfigyelő reports 106 Auchan `LOYALTY` prices if needed |
| 5 | **Day-over-day stability** | Two full crawls (16th/17th): 15,031 → 15,038 products, 14,976 common, 55 gone, 62 new. **0 EAN changes, 0 product-ID or variant-ID changes.** Price changed on 1,126 (7.5%), discount flag on 267, availability on 70 |

Data-model notes from the crawl:

- No multi-variant products (`selectedVariant` is the product).
- 148 weighed items (`loose: true`, unit `kg`): use `packageInfo.unitPrice` (per kg).
- `packageUnit`: KG 7,666, LITER 4,570, DB 2,771, M 24. `unitPrice` equals price ÷ `packageSize` except for 114 products.
- Useful flags: `Auchan Kedvenc` (own brand, 1,042), `ÁrrésCsökkentés` (margin cap, 689), `Kiemelt ajánlat`, `Kifutó termék`.
- Detail endpoints (`details/description`, `details/ingredients`, `details/nutrition`, `details/parameterList`) provide text for embeddings. Fetch them only for new or changed products.
- Tesco `gtin` is stored as GTIN-14 with leading zeros (`00000054026193`); normalise by stripping leading zeros before joining.
- Tesco `deposit_amount` is missing in the tracker. Cause (2026-09-17): the
  scraper writes product metadata (`gtin`, `deposit_amount`, …) only on a
  product's first full fetch and strips empty values; `depositAmount` was added
  to the GraphQL query on 2026-05-01, so products first seen before then never
  received it. A fix needs a periodic metadata refresh, which adds Tesco
  requests while the scraper already hits rate limits, so it is deferred.

## 8. Recommendation

| Source | Gives | Role |
|---|---|---|
| Tesco (existing scraper) | Full range, daily | Primary store |
| GVH Árfigyelő | Daily normal/discount/loyalty prices, 9 chains, basic categories, **GTIN keys** | The "several webshops" comparison; GTIN matches are ground truth for evaluating embedding-based matching |
| penny.hu API | Penny leaflet: promotions with future validity windows, images, unit prices | Promotion and "upcoming price drop" data, joined to Árfigyelő via `penny-{n}` = `86-{n}` |

If a second store with a Tesco-like **full** daily range is still wanted,
investigate a chain that sells online (Auchan, SPAR, Kifli.hu) next.

## 9. Open questions

- SKU stability across offer weeks (step 5.3).
- Meaning of the `IO` / `SO` / `pt-*` tags.
- penny.hu terms of use for automated collection.
- Whether Árfigyelő caps the chains shown per product at 3.
- Árfigyelő search parameter name; whether past prices are exposed through the API.
- GVH's answer on reuse and an official export.
