# Decision records

Why the design is the way it is. One page each: the situation, what was
decided, and what it costs. They are not updated when the code changes - a
decision that no longer holds gets a new record that supersedes it.

| # | Decision |
|---|---|
| [1](0001-one-collection-per-store.md) | One collection per store, with a shared offer layer |
| [2](0002-barcode-as-the-cross-store-key.md) | The barcode is the cross-store product key |
| [3](0003-store-switches-in-the-database.md) | Store switches live in the database, not in configuration |
| [4](0004-auchan-card-prices.md) | Auchan card prices: accept partial coverage and label it |
| [5](0005-hybrid-semantic-search.md) | multilingual-e5-small, Qdrant, and Reciprocal Rank Fusion |
| [6](0006-store-neutral-naming.md) | Store-neutral naming, with the old route kept as an alias |
| [7](0007-per-service-mongodb-accounts.md) | Per-service MongoDB accounts, with a visible fallback |
| [8](0008-learned-category-mapping.md) | The cross-store category mapping is learned, not configured |
| [9](0009-cross-store-recommendations.md) | Recommendations are content-based, and about products rather than listings |
