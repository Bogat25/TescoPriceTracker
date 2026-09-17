# Semantic and hybrid search

How the price tracker finds products by meaning, not only by the words in
their names: what the parts are, which technologies they use and why, how data
flows through them, how it is operated, and how its quality was measured.

Status: implemented in Phase 6 (see [upgrade-plan.md](upgrade-plan.md)).
Measured results: [search-eval.md](search-eval.md).

---

## 1. What it does

| Feature | Before | Now |
|---|---|---|
| Search | MongoDB text index on product names: finds a product only if the query contains a word from its name | **Hybrid search**: text matches and meaning matches fused into one ranking, across the selected stores |
| "üdítő" (soft drink) | products with "üdítő" in the name | also colas, lemonades, iced teas, flavoured waters |
| "gluténmentes kenyér" | only names containing both words | gluten-free breads, rolls and toast, whatever they are called |
| English or misspelled queries | usually nothing | often the right products (the model is multilingual) |
| Similar products | none | "Similar products" on every product page, from every store |
| Vectors | built on a laptop, Tesco only | built in the cluster, all stores, automatically |

Barcodes and numeric IDs still use exact text search: meaning adds nothing there.

---

## 2. Architecture

```
                    ┌────────────────────────── indexing (every 30 min) ─────────────────────────┐
                    │                                                                            │
 products (Tesco) ──┤                                                                            │
 auchan_products ───┼──► vectorizer ──texts──► embedding-service ──vectors──► vectorizer ──► Qdrant "offers"
                    │    (hash check:          (E5-small, PyTorch CPU)                   (1 point per offer,
                    │     only new/changed)                                               payload: store, ref,
                    │         │                                                           group_id, category)
                    │         └──► Mongo embedding_state {ref, hash}                                   │
                    └────────────────────────────────────────────────────────────────────────────┘   │
                                                                                                       │
                    ┌───────────────────────────── query (per request) ────────────────────────┐      │
  GET /search?q=…   │                                                                          │      │
  &stores=…&mode=…  │   for each selected store:                                               │      │
  ──────────────► api ──► text index (Mongo $text) ── ranking A ──┐                            │      │
                    │ └─► embedding-service (query vector, cached) │                            │      │
                    │         └─► Qdrant nearest, filter store ──── ranking B ◄─────────────────┼──────┘
                    │                                              ▼                            │
                    │                         Reciprocal Rank Fusion (A, B)                     │
                    │   interleave stores by rank → group by barcode → fill missing stores       │
                    │   → product rows (one row per product, a price per store)                  │
                    └──────────────────────────────────────────────────────────────────────────┘
```

Containers (all on the stack's internal network, none published):

| Container | Image | Role |
|---|---|---|
| `embedding-service` | `tesco-tracker-embedding` (new) | Turns texts into 384-dimensional vectors |
| `vectorizer` | `tescopricetracker` (shared backend image) | Keeps Qdrant in step with every enabled store's catalogue |
| `qdrant` | `qdrant/qdrant:v1.17` (existing) | Vector index with payload filters |
| `api` | `tescopricetracker` (existing) | Runs hybrid search, similar products, recommendations |
| `mongo` | existing | Product documents, text index, `embedding_state` |

---

## 3. Technologies and why they were chosen

### 3.1 Embedding model: `intfloat/multilingual-e5-small`

An **embedding** maps a text to a point in a vector space so that texts with
similar meaning land close together. Closeness is measured with **cosine
similarity** (the angle between two vectors; 1 = same direction).

E5 ("EmbEddings from bidirEctional Encoder rEpresentations", Wang et al.,
2022) is a transformer encoder trained contrastively on large amounts of
query–passage pairs, so "gluténmentes reggeli" and a gluten-free muesli's
description end up close. The multilingual variant is initialised from
multilingual MiniLM and trained on ~100 languages, including Hungarian.

| Property | Value |
|---|---|
| Parameters | 118 M (12 layers, hidden size 384) |
| Output | 384 dimensions, mean pooling over tokens, L2-normalised |
| Input limit | 512 tokens (longer texts are truncated) |
| Tokenizer | SentencePiece (XLM-R vocabulary, handles Hungarian accents and compounds) |
| Licence | MIT |
| Pinned revision | `614241f622f53c4eeff9890bdc4f31cfecc418b3` |

**Query and passage prefixes.** E5 was trained with role markers: search text
is encoded as `query: …`, documents as `passage: …`. Retrieval is
*asymmetric* (a two-word query against a paragraph), and the prefixes tell the
model which side it is encoding. Forgetting them measurably lowers quality, so
the embedding service adds them itself and callers only say `mode: query` or
`mode: passage`.

**Why this model:**

| Option | Why not (or why) |
|---|---|
| **multilingual-e5-small** ✅ | Good Hungarian retrieval for its size; fast on a CPU; already used by the earlier laptop worker, so the design was proven |
| multilingual-e5-base / large | 2.4× / 4.7× the parameters and roughly that much slower on CPU; the catalogue texts are short, so the small model's quality is sufficient |
| paraphrase-multilingual-MiniLM-L12-v2 | Trained for sentence similarity, not query→document retrieval; no query/passage roles |
| LaBSE | Built for translation pairs; weaker for retrieval, 471 M parameters |
| Hosted APIs (OpenAI, Cohere …) | Per-request cost, an external dependency on every search, and every query sent to a third party |
| Plain BM25 / text index only | No synonyms, no intent ("sörkorcsolya" → snacks), no English or typo tolerance |

### 3.2 Runtime: sentence-transformers on PyTorch (CPU)

`sentence-transformers` loads the model, tokenises, runs the transformer and
applies the pooling and normalisation the model was published with, so the
service produces exactly the vectors the model authors intended. PyTorch runs
it on the CPU; the **CPU-only wheel** is installed (the default wheel bundles
CUDA libraries, several GB the server cannot use).

Verified: vectors from the container match a local reference run of the same
model revision to within 5·10⁻⁸.

Considered: ONNX Runtime would give a smaller image and some extra speed, but
needs a model export step and a second code path to keep equivalent. The
measured PyTorch speed (§6) is already far above what the catalogue needs.

### 3.3 Why a separate embedding service

* **One model in memory** (~700 MB) shared by the API (query vectors) and the
  vectorizer (product vectors), instead of one copy per process.
* **Isolation of heavy dependencies**: PyTorch stays out of the Alpine backend
  image all other services use.
* **Resource limits**: the container is capped at 4 CPUs and 1.5 GB, so a
  full re-embedding cannot starve the scrapers or the API on the shared host.
* **Replaceable**: a different model or runtime only changes this container;
  the vectorizer notices the new model name and re-embeds everything.

The model files are **baked into the image** at a pinned revision: the
container needs no internet access, starts in ~2 s, and every build yields the
same weights (vectors from different deploys stay comparable).

### 3.4 Vector database: Qdrant

Qdrant was already part of the stack. It stores each vector with a JSON
**payload** and answers nearest-neighbour queries with an **HNSW** graph index
(approximate search in logarithmic time). The features used here:

* **Payload filters inside the vector search** (`store IN [...]`, `group_id != …`),
  applied during graph traversal, so filtering does not lose results the way
  filtering after a top-k search would.
* **Keyword payload indexes** on `store`, `ref`, `group_id`, `category`.
* **Cosine distance** on normalised vectors.
* **Score threshold** (`score_threshold`) to drop weak semantic matches.

Collection `offers`: one point per store offer. Point ID =
`uuid5(namespace, "tesco:123")`, so re-embedding a product overwrites its
point, and any component can compute a product's point ID from its reference.

| Payload field | Example | Used for |
|---|---|---|
| `ref` | `auchan:678170` | mapping a hit back to the store document |
| `store` | `auchan` | store selection filter |
| `product_id` | `678170` | recommendation engine (Tesco tpnc) |
| `group_id` | `g:5998…` | "similar products" excludes the product itself in every store |
| `gtin_norm` | `5998…` | diagnostics |
| `category` | `Tejtermékek` | category buckets in personal recommendations |
| `name` | `Auchan zabpehely 500 g` | diagnostics |

### 3.5 Text retrieval: MongoDB text index

The existing text indexes (Tesco: `name`; Auchan: `name`, `brand`, language
`none`) stay the **lexical** half of hybrid search. They are exact and cheap,
and they win for brand names, product codes and rare words the embedding
model may blur (e.g. "Pöttyös", "Milka").

### 3.6 Fusion: Reciprocal Rank Fusion (RRF)

The text index returns a relevance score on one scale, Qdrant a cosine
similarity on another; neither can be compared or averaged meaningfully.
**RRF** (Cormack, Clarke & Büttcher, SIGIR 2009) ignores scores and uses only
ranks:

```
score(d) = Σ over rankings r   1 / (k + rank_r(d))        k = 60, rank starts at 1
```

A product ranked well by *both* retrievers beats one ranked first by only one
of them; a product found by only one retriever still appears. `k = 60` is the
value from the original paper; it keeps the top of each list from dominating.
RRF needs no training data and no score calibration, which matters for a
catalogue with no click logs.

Fusion runs **per store**, then stores are interleaved by fused rank, the same
store-neutral merge the text search already used: no store is favoured, and a
store with longer descriptions does not push the other store's results down.

### 3.7 Incremental indexing: content hashing

The vectorizer does not rely on "changed" flags from the scrapers. For every
product it rebuilds the embedding text and hashes it together with the model
identity:

```
hash = sha256(model_name@revision + "\n" + embedding_text)
```

and compares it with `embedding_state` (`{_id: ref, store, hash, embedded_at}`).
Only products whose hash differs are embedded. Consequences:

* the first pass embeds everything; later passes embed only new products and
  products whose name, category or description changed;
* an Auchan description arriving days later (the crawler fetches details
  gradually) automatically re-embeds that product;
* deploying a different model re-embeds the whole catalogue with no manual step;
* products that disappear from a catalogue have their point deleted.

---

## 4. Data flow in detail

### 4.1 What text is embedded

Built by `stores/embedding_text.py`. Only descriptive content: prices, IDs,
URLs and legal boilerplate would make vectors change for reasons unrelated to
what the product *is*. Labels are Hungarian, matching the product texts.

| Store | Fields (in order) |
|---|---|
| Tesco | name · `Márka:` brand (sub-brand) · `Kategória:` department › aisle › shelf · short description · `Marketing:` text · `Jellemzők:` features · `Összetétel:` nutritional claims · `Összetevők:` first 5 ingredients |
| Auchan | name · `Márka:` brand · `Kategória:` category path · description (≤800 chars) · `Összetevők:` ingredients (≤300 chars) |

Example (Auchan):

```
Auchan zabpehely 500 g. Márka: Auchan. Kategória: Élelmiszer, Reggeli. Teljes kiőrlésű zabpehely. Összetevők: zab
```

Texts are capped at 2,000 characters (~500 tokens, the model's limit).
Products with nothing more than a very short name are skipped.

### 4.2 Indexing pass (`stores/vectorize.py`)

1. Ask the embedding service for its model identity (`GET /info`).
2. Ensure the `offers` collection and its payload indexes exist.
3. For each **enabled** store in the registry: stream its products from
   MongoDB (only text fields), build texts, compare hashes, collect changed
   products in batches of 64 → `POST /embed` (`mode: passage`) → upsert points
   → record hashes.
4. Delete points of products no longer in the store's collection.
5. Log `vectorize.store_synced` per store (counts, duration) and
   `vectorize.completed`; on any failure log `vectorize.failed` and retry in
   five minutes. Progress is saved per batch, so a failed pass resumes where it
   stopped.

### 4.3 Search request (`stores/queries.py`)

`GET /api/v1/search?q=…&stores=tesco,auchan&mode=hybrid&skip=0&limit=50`

1. Barcode or numeric query → text search only.
2. Query vector from the embedding service (`mode: query`); the last 512
   distinct queries are cached in the API process.
3. For each selected store:
   * text ranking: up to 200 results from the store's text index;
   * semantic ranking: up to 200 nearest offers in Qdrant with `store = …` and
     cosine similarity ≥ `SEMANTIC_MIN_SCORE`, loaded from MongoDB in rank order;
   * RRF of the two rankings.
4. Interleave stores by rank; group offers by barcode; take the requested page;
   add the other selected stores' offers of each product; build rows.
5. The response carries `mode`: `hybrid`, `semantic` or `text`.

`mode=semantic` skips the text index; `mode=text` is the old behaviour (used
by the search box's live suggestions, where every keystroke must be fast).

**Fallback:** if the embedding service or Qdrant fails, the request is
answered with text search, `mode: "text"`, and `search.semantic_unavailable` is
logged. Search never fails because of the semantic path.

### 4.4 Similar products

`GET /api/v1/groups/{group_id}/similar?stores=…` and
`GET /api/v1/offers/{ref}/similar?stores=…`

The vectors of the product (for a group: every store's offer, averaged) are the
query; Qdrant returns the nearest offers in the selected stores, excluding the
product's own group, so "similar" never lists the same product from another
store. Results are grouped into rows like search results. Shown on the
comparison page.

### 4.5 Personal recommendations

The recommendation engine (see `backend-api/recommendation_engine.py`) reads
the same `offers` collection: for each category the user has alerts in, it
averages the alerted products' vectors and searches the nearest Tesco products
in that category, then scores candidates by similarity and discount. It filters
`store = tesco` because the category buckets use Tesco's category names;
cross-store personal picks need a shared category mapping (Phase 9).

---

## 5. Similarity threshold

E5 similarities fall in a narrow band: in the verification run,
"gluténmentes reggeli" scored 0.856 against a gluten-free muesli and still
0.817 against Coca-Cola. Without a threshold, pure semantic search returns the
"least unrelated" products even for nonsense. `SEMANTIC_MIN_SCORE` drops weak
matches.

Calibrated with `scripts/search_eval.py --calibrate` against the live
catalogue (full table in [search-eval.md](search-eval.md)):

| Threshold | Semantic P@10 | Results for 4 off-catalogue queries |
|---|---|---|
| 0.80 | 0.84 | 40 |
| **0.82** | **0.82** | **24** |
| 0.84 | 0.77 | 20 |
| 0.86 | 0.57 | 1 |

**0.82 is the deployed value**: it removes 40 % of the weak matches for two
points of precision. Pushing to 0.86 does clear the noise, but costs a third of
the real results, which is the wrong trade for a shop where a missing product
is worse than an odd one at the bottom of the list.

The remaining off-catalogue results are not random: "autógumi téli" returns
"Téli Puncs" air freshener, "laptop töltő 65w" returns a 3D-pen refill — the
model is matching a real word in the query. No single threshold separates those
from genuine loose matches. Hybrid search is less sensitive to all of this,
because text matches rank first through RRF anyway.

---

## 6. Performance and capacity

Measured, not estimated:

| Measurement | Result |
|---|---|
| Model load (container, baked files) | 1.8 s |
| Throughput, container limited to 4 CPUs (Linux, i7-13650HX) | 172 passages/s |
| Throughput, laptop Windows, 6 threads / 4 threads | 93 / 82 passages/s (typical 92-token product text) |
| Single query vector | 7–8 ms |
| Container memory after warm-up | 707 MiB (limit 1.5 GiB) |
| Image size | 2.7 GB (PyTorch CPU 0.9 GB, model 0.5 GB) |

**Production host: Intel Core i5-12500** (6 performance cores / 12 threads,
AVX2 and AVX-VNNI). Its per-core speed is close to the i7-13650HX used for the
measurements, and the container gets the same 4-CPU limit, so the same order of
magnitude applies. The service logs its own measured throughput at every start
(`embedding.ready`, `PassagesPerSecond`), so the real value on the host is
visible in Grafana.

Catalogue: 22,708 Tesco + 15,036 Auchan products ≈ 37,700 texts.

* First full indexing: 37,700 ÷ ~80–170 passages/s ≈ **4–8 minutes** of CPU
  (plus MongoDB reads and Qdrant writes).
* Daily changes: hundreds of products → **seconds**.
* Query latency added by semantic search: ~10 ms embedding (0 ms when cached)
  + a few ms of Qdrant per store + one MongoDB lookup of ≤200 IDs per store.
* Qdrant memory: 37,700 × 384 float32 ≈ 58 MB of vectors plus the HNSW graph.

---

## 7. Operations

### 7.1 Configuration

| Variable | Where | Default | Meaning |
|---|---|---|---|
| `EMBEDDING_THREADS` | embedding-service | 4 | PyTorch intra-op threads |
| `EMBEDDING_CPUS` / `EMBEDDING_MEMORY_LIMIT` | compose | 4 / 1536m | container limits |
| `EMBEDDING_SERVICE_URL` | api, vectorizer | `http://embedding-service:8080` | |
| `QDRANT_OFFERS_COLLECTION` | api, vectorizer | `offers` | |
| `SEMANTIC_MIN_SCORE` | api | 0.82 | similarity threshold (§5) |
| `VECTORIZE_INTERVAL_SECONDS` | vectorizer | 1800 | pass interval |
| `VECTORIZE_BATCH_SIZE` | vectorizer | 64 | texts per embedding request |

No new secrets. Qdrant is reached with the existing `QDRANT_API_KEY`.

### 7.2 Logs and alerts

| Action | Service | Meaning |
|---|---|---|
| `embedding.ready` | embedding-service | model loaded; load time and measured throughput |
| `vectorize.store_synced` | vectorizer | per store: embedded, unchanged, without text, removed, duration |
| `vectorize.completed` / `vectorize.failed` | vectorizer | pass outcome |
| `search.semantic_unavailable` | backend-api | a search fell back to text |

Grafana rules (Observability repo, `semantic-search-rules.yaml`):
`vectorizer-failing` (three failed passes in a row), `vectorizer-stale` (no
completed pass for 3 h), `semantic-search-degraded` (>10 fallbacks in 15 min).

### 7.3 Failure modes

| Failure | Effect | Recovery |
|---|---|---|
| embedding-service down or loading | search answers with text (`mode: text`); similar products 503; vectorizer pass fails | automatic when the container is healthy; vectorizer retries every 5 min |
| Qdrant down | same as above | automatic |
| Vectorizer stopped | search keeps working with the vectors it has; new products are found by text only | restart; the next pass catches up by hash |
| Model changed | vectors of the new model are not comparable with old ones | automatic: hashes include the model, the next pass re-embeds all |
| Collection deleted | semantic results empty until re-indexed | delete `embedding_state` too (or it will think all is current), then the next pass rebuilds |

### 7.4 Trust boundary

* The embedding service has **no published port and no ingress route**; it is
  reachable only from containers on `tesco-tracker-internal`.
* It stores nothing and exposes no data: its only function is text → vector.
  The worst misuse from inside the network is CPU load, bounded by its
  container limits. Those containers can already read MongoDB directly, so a
  token would not add a meaningful boundary; it has none, deliberately.
* Qdrant keeps its API key. The public API exposes only search results and
  similar products, never vectors.
* The legacy laptop sync (`recommendation-api`, `vector-creation-script`) is
  no longer needed; it stays until the Phase 9 clean-up.

---

## 8. API reference

| Endpoint | Parameters | Returns |
|---|---|---|
| `GET /api/v1/search` | `q`, `stores`, `skip`, `limit`, `mode` = `hybrid` (default) \| `semantic` \| `text`, `min_score` (0–1, calibration only) | row page + `mode` actually used |
| `GET /api/v1/groups/{group_id}/similar` | `stores`, `limit` ≤ 48 | `{results: rows}` (empty until the product has vectors) |
| `GET /api/v1/offers/{ref}/similar` | `stores`, `limit` ≤ 48 | `{results: rows}` |
| `POST embedding-service:8080/embed` | `{texts: [≤128 strings], mode: query \| passage}` | `{vectors, model, dimension}` |
| `GET embedding-service:8080/info` | – | model, revision, dimension, threads |
| `GET embedding-service:8080/health` | – | 200 when the model is loaded |

Public routes are the same under the gateway prefix `/api/tesco/*`.

---

## 9. Evaluation method

`scripts/search_eval.py` sends 30 Hungarian queries to the live API in each
mode and scores the top 10 rows. Query kinds: *literal* (the product word is in
the name), *intent* (need, synonym or category: "sörkorcsolya", "kenyérre
kenhető"), *typo* and *English*. Relevance is decided by regular-expression
rules over offer names and category paths, written before looking at results,
so no mode is favoured by hand-labelling.

Metrics: **precision@10** (relevant rows among the first 10), **MRR** (mean
reciprocal rank of the first relevant row), zero-result queries, median
latency. `--calibrate` sweeps the similarity threshold and counts results for
nonsense queries. Results and the chosen threshold: [search-eval.md](search-eval.md).

Limitations of the method: rule-based relevance is stricter than a human judge
for broad intents (a relevant product whose name does not match the pattern
counts as a miss) and 30 queries give an indication, not statistical
significance.

---

## 10. Limitations and next steps

* **Auchan descriptions arrive gradually** (the crawler fetches ≤300 product
  details per day), so many Auchan products are embedded from name, brand and
  category only at first; they are re-embedded automatically when details
  arrive.
* **No cross-encoder re-ranking.** A re-ranker would sharpen the top results
  but costs ~10–50× the CPU per query.
* **Personal recommendations use Tesco categories** (§4.5); cross-store
  personal picks wait for a category mapping.
* **Quantity and price intent** ("olcsó", "1 literes") are not understood by
  the model; they belong to filters, not embeddings.
* **Product linking without barcodes** (embedding + brand + pack size) is a
  possible later use of the same vectors.

## References

* L. Wang et al., *Text Embeddings by Weakly-Supervised Contrastive Pre-training* (E5), 2022. arXiv:2212.03533
* L. Wang et al., *Multilingual E5 Text Embeddings: A Technical Report*, 2024. arXiv:2402.05672
* G. Cormack, C. Clarke, S. Büttcher, *Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods*, SIGIR 2009
* Y. Malkov, D. Yashunin, *Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs*, 2016. arXiv:1603.09320
* N. Reimers, I. Gurevych, *Sentence-BERT*, EMNLP 2019 (sentence-transformers)
