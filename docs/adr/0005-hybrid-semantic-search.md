# 5. multilingual-e5-small, Qdrant, and Reciprocal Rank Fusion

**Status:** accepted, 2026-09-17 (decision D2 for the host)

## Context

Mongo's text index answers "tej 1,5" well and "mivel kenjem a kenyeret" not at
all. Hungarian compounds and inflections make a text index worse here than in
English, and a shopper's query is often a description rather than a product
name. But pure vector search is worse at the other end: exact names, brands and
barcodes, where the literal match is the right answer.

The embedding worker also ran by hand on a laptop, outside Docker, which made
the search quality of production depend on somebody's machine being awake.

## Decision

- **Model:** `intfloat/multilingual-e5-small` (384 dimensions), in its own
  container on the same host as everything else, CPU only. It is small enough
  to embed the whole catalogue in 4-8 minutes and answer a query in 7-8 ms, and
  it handles Hungarian.
- **Store:** Qdrant, one point per offer, the point id derived from the offer
  `ref` so re-embedding overwrites rather than duplicates. Payload fields allow
  filtering by store and excluding a product's own group.
- **Ranking:** hybrid by default. Text and vector results are fused per store
  with **Reciprocal Rank Fusion** (`1 / (60 + rank)`), which uses only ranks -
  the text score and the cosine similarity never have to be put on the same
  scale.

Measured: P@10 of 0.78 text, 0.82 semantic, **0.87 hybrid**
([search-eval.md](../search-eval.md)).

## Consequences

- Search degrades instead of failing. If the embedding service or Qdrant is
  unavailable, the query is answered from the text index and the response says
  `"mode": "text"`.
- A numeric query (a barcode or product id) skips the vector path: only an
  exact match makes sense there.
- Two systems must be kept in step. Documents carry `needs_revector`, and the
  vectorizer embeds only what changed and deletes points whose offer is gone.
- The similarity threshold is not intuitive: E5 scores sit in a narrow band and
  unrelated texts still score ~0.7, so a minimum of 0.82 was calibrated rather
  than guessed.
- Filtering by category cannot be pushed into the vector query the way it is
  pushed into Mongo, because a point's payload category is the store's own; the
  category filter is applied to the offers after they are read.
