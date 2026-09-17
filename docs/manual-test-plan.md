# Manual test plan

What a person has to check in a browser, because it cannot be verified from the
outside: anything behind a login, anything visual, and anything that depends on
a real browser extension. Everything else is covered by
`scripts/api_smoke.py` (19 automated checks) and the unit tests.

Site: https://price-tracker.gavaller.com

How to use this: work top to bottom, tick what passes, and note anything odd in
the "Notes" column. Tests marked **P7** or **P8** only make sense after the
Phase 7/8 deploy.

---

## 1. Search and browsing (no login)

| # | Step | Expected | ✓ | Notes |
|---|---|---|---|---|
| 1.1 | Open the home page | Loads, no store named in the header, footer or hero text (**P7**: "Price Tracker") | | |
| 1.2 | Type `tej` in the search box, wait | Suggestions drop down within a second, each showing a store name and a price | | |
| 1.3 | Press Enter | Result rows appear, each with one price per store, cheapest highlighted | | |
| 1.4 | Search `gluténmentes kenyér` | Gluten-free breads, not just names containing both words | | |
| 1.5 | Search `sörkorcsolya` (or another "intent" phrase) | Snack-type products, nothing absurd in the top 5 | | |
| 1.6 | Search a barcode, e.g. `5449000000996` | The exact product, or nothing — never unrelated items | | |
| 1.7 | Search something you know only Auchan sells | The Auchan row appears | | |
| 1.8 | Untick a store in the store chips | Results reload with only the other store; the choice survives a page reload | | |
| 1.9 | Open the catalogue and sort by price and by discount | Order matches the numbers shown | | |
| 1.10 | Page to page 2 and back | Rows change, no duplicates, the URL keeps the page | | |

## 2. Product pages

| # | Step | Expected | ✓ | Notes |
|---|---|---|---|---|
| 2.1 | Open a product sold by both stores | Comparison table with a row per store: regular, promo, card price, unit price, date | | |
| 2.2 | Check the cheapest marker | The lowest actual price is marked, not just the first row | | |
| 2.3 | Price history chart | One line per store, no gaps that should not be there; range buttons work | | |
| 2.4 | "Open in store" links | Both open the right product in the right shop | | |
| 2.5 | Scroll to **Similar products** | Related products, not the same product from the other store | | |
| 2.6 | Open a Tesco-only product | The rich Tesco page still works (description, ingredients, stats) | | |
| 2.7 | Open an Auchan-only product | The offer page shows price, history and store link | | |
| 2.8 | Card-price note | The comparison page says Auchan card prices are only partly known | | |

## 3. Alerts (needs login)

| # | Step | Expected | ✓ | Notes |
|---|---|---|---|---|
| 3.1 | Log in | Returns to the site signed in; no redirect loop | | |
| 3.2 | Open **Alerts** | Your existing alerts are listed, each showing "Stores: Tesco" (they were migrated) | | |
| 3.3 | Check names and prices | Real product names and current prices, not bare IDs | | |
| 3.4 | Open a comparison page → price alert form | Store chips appear for a product sold by both stores | | |
| 3.5 | Create a target-price alert with both stores ticked | Saved; appears on the Alerts page with both store names | | |
| 3.6 | Create one with only Auchan ticked | Saved; shows only Auchan | | |
| 3.7 | Try a target price above the current price | Refused with a clear message | | |
| 3.8 | Create a % drop alert | Saved; the base price is the lowest of the ticked stores | | |
| 3.9 | Toggle an alert off and on | State survives a page reload | | |
| 3.10 | Delete an alert | Disappears and stays gone after reload | | |
| 3.11 | Email preference toggle | Saves, survives reload | | |
| 3.12 | Home page alerts panel | Shows your latest alerts with names and links | | |
| 3.13 | Log out, open /alerts | Sign-in prompt, no data leaks | | |

*Only when a price actually drops:* the email arrives, names the store, and the
link opens the right product.

## 4. Recommendations

| # | Step | Expected | ✓ | Notes |
|---|---|---|---|---|
| 4.1 | Open search while logged out | "Trending deals" rows with prices per store | | |
| 4.2 | Log in, open search | Picks related to your alerted products | | |
| 4.3 | Untick a store, reload | Recommendations respect the store choice | | |

## 5. Statistics

| # | Step | Expected | ✓ | Notes |
|---|---|---|---|---|
| 5.1 | Open Statistics | Store tabs; numbers load without spinning forever | | |
| 5.2 | Switch store tabs | Values change per store | | |
| 5.3 | "Compare stores" tab | Price index, cheapest counts and overlap look sane | | |
| 5.4 | Click a price-drop item | Opens the right product in the right store | | |

## 6. Language, layout, errors

| # | Step | Expected | ✓ | Notes |
|---|---|---|---|---|
| 6.1 | Switch HU ↔ EN | Everything translates; no raw keys like `alertform.title` | | |
| 6.2 | Phone-width browser | Search, rows, comparison table and alert form usable, nothing cut off | | |
| 6.3 | Dark/light mode (if used) | Prices and badges readable in both | | |
| 6.4 | Open a made-up product URL | "Not found" page, not a crash | | |
| 6.5 | Search gibberish (`xqzvbt`) | Empty state with a hint, not an error | | |

## 7. Browser extension

| # | Step | Expected | ✓ | Notes |
|---|---|---|---|---|
| 7.1 | Open a Tesco product page with the extension installed | Price history chart appears | | |
| 7.2 | Extension alert actions | Creating/removing an alert still works and shows up on the site | | |
| 7.3 | **P7** After the route change | Extension keeps working (it uses the old `/api/tesco` route on purpose) | | |

## 8. After the Phase 7 / 8 deploy

| # | Step | Expected | ✓ | Notes |
|---|---|---|---|---|
| 8.1 | **P7** Site name | No store in the header, footer, page titles (browser tab) or privacy policy | | |
| 8.2 | **P7** Privacy policy | Mentions both stores as data sources; "not affiliated with any store" | | |
| 8.3 | **P7** Open the site and check the network tab | Catalogue calls go to `/api/prices/…` and return 200 | | |
| 8.4 | **P8** Log in again after the deploy | Session still works (auth was not touched) | | |
| 8.5 | **P8** mongo-express | Not reachable any more unless the stack is deployed with `COMPOSE_PROFILES=admin-tools` | | |

*I verify from my side:* per-service MongoDB accounts in use (no
`mongo.root_credentials` warnings), no new errors after deploy, the first
Auchan price-drop alerts, and fewer Tesco 429s over the next scrape days.

---

## Reporting a problem

Useful in a report: the page, what you did, what you expected, what happened,
and — if it's a data problem — the product link. For a visual problem a
screenshot beats a description.
