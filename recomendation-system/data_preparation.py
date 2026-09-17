"""Embedding text for the legacy laptop vector sync (Tesco only).

The text is built by ``stores.embedding_text``, shared with the in-cluster
vectorizer, so both produce the same input for the same product.
"""

from typing import Optional

from stores.embedding_text import tesco_text


def build_embedding_text(product: dict) -> Optional[str]:
    return tesco_text(product)
