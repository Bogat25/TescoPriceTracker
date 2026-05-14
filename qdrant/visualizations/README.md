# Qdrant Visualisations

Five queries for the Qdrant Web UI's **Visualize** tab against the
`products` collection.

## How to run

1. Open the dashboard: `http://<pi-tailnet-ip>:6333/dashboard`
2. Paste the API key from `.env.prodversion` (`QDRANT_API_KEY`).
3. **Collections → products → Visualize** tab.
4. Paste a query, hit **▶ RUN**, wait 5–60s for the projection.

Hover any dot to see its payload (`product_id`, `category`).

## The queries

### `01-category-overview.json`
2,000 random products, coloured by category. Default UMAP — gives the
broadest "what's in the catalogue" view. Start here.

### `02-dense-cluster-zoom.json`
5,000 points with t-SNE instead of UMAP. t-SNE separates dense local
neighbourhoods more aggressively, so visually similar products bunch
into tight, sharply-edged blobs. Slower to compute — give it 30–60s.

### `03-drinks-only.json`
Filtered to drink-related categories (juice, soft drinks, wine, beer,
water, coffee, tea). Smaller, cleaner plot where you can see the
sub-clusters within "drinks" — e.g. red wine vs white wine, instant
coffee vs ground.

### `04-fresh-vs-frozen.json`
Filtered to fresh / chilled / frozen products with tighter UMAP
parameters (`n_neighbors=30, min_dist=0.05`) for sharper local
structure. Good for spotting where the same product type splits between
fresh and frozen aisles.

### `05-similar-to-product.json`
"Show me 500 products most similar to this one." Replace
`123456789012345` with a real Qdrant point ID — get one from the
**Points** tab. The plot becomes radial: the seed product at the
centre, similar products pulled in close.

## Notes on the schema

The Qdrant payload only stores `product_id` (string) and `category`
(string). Anything else — name, brand, price — lives in MongoDB and
is not visible in these plots. To add richer hover data you'd need a
custom HTML viewer that joins Qdrant points with MongoDB records.
