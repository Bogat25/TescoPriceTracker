"""AI Worker Node — Vector Generation Script.

This script runs on the laptop (worker node) and:
1. Polls Service B for products needing vectorization
2. Generates 384-dim embeddings using intfloat/multilingual-e5-small
3. Pushes the resulting vectors back to Service B

Requirements:
    pip install sentence-transformers requests python-dotenv

Usage:
    python worker.py                    # Single run
    python worker.py --loop             # Continuous polling mode
    python worker.py --loop --interval 60  # Poll every 60 seconds
"""

import argparse
import logging
import os
import sys
import time
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

SERVICE_B_BASE_URL = os.environ.get(
    "SERVICE_B_BASE_URL", "http://localhost:8090"
).rstrip("/")
VECTOR_SYNC_API_TOKEN = os.environ.get("VECTOR_SYNC_API_TOKEN", "")
BATCH_SIZE = int(os.environ.get("WORKER_BATCH_SIZE", "100"))
MAX_RETRIES = int(os.environ.get("WORKER_MAX_RETRIES", "3"))
RETRY_DELAY = int(os.environ.get("WORKER_RETRY_DELAY", "5"))

# Model configuration
MODEL_NAME = "intfloat/multilingual-e5-small"


def get_headers() -> dict:
    """Build auth headers for Service B."""
    return {
        "Authorization": f"Bearer {VECTOR_SYNC_API_TOKEN}",
        "Content-Type": "application/json",
    }


def load_model():
    """Load the sentence-transformers model. Downloads on first run."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        logger.error(
            "sentence-transformers not installed. Run: pip install sentence-transformers"
        )
        sys.exit(1)

    logger.info(f"Loading model: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)
    logger.info("Model loaded successfully.")
    return model


def fetch_products(batch_size: int = BATCH_SIZE) -> Optional[list[dict]]:
    """Fetch un-vectorized products from Service B.

    Returns None on connection failure, empty list if no products need processing.
    """
    url = f"{SERVICE_B_BASE_URL}/api/internal/products/sync"
    params = {"limit": batch_size}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, headers=get_headers(), params=params, timeout=30)
            if response.status_code == 401:
                logger.error("Authentication failed. Check VECTOR_SYNC_API_TOKEN.")
                return None
            response.raise_for_status()
            products = response.json()
            logger.info(f"Fetched {len(products)} products for vectorization")
            return products
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Connection failed (attempt {attempt}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
        except requests.exceptions.Timeout:
            logger.warning(f"Request timed out (attempt {attempt}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error: {e}")
            return None

    logger.error("Max retries reached. Could not fetch products.")
    return None


def generate_embeddings(model, products: list[dict]) -> list[dict]:
    """Generate vector embeddings for a batch of products.

    The E5 model requires the prefix "passage: " for document embeddings.
    """
    if not products:
        return []

    # Prepend "passage: " as required by the E5 model
    texts = [f"passage: {p['embedding_text']}" for p in products]

    logger.info(f"Generating embeddings for {len(texts)} products...")
    embeddings = model.encode(texts, show_progress_bar=True, normalize_embeddings=True)

    results = []
    for product, embedding in zip(products, embeddings):
        results.append({
            "mongo_id": product["mongo_id"],
            "category": product.get("category"),
            "vector": embedding.tolist(),
        })

    logger.info(f"Generated {len(results)} embeddings")
    return results


def push_vectors(vectors: list[dict]) -> bool:
    """Push completed vectors back to Service B.

    Returns True on success, False on failure.
    """
    if not vectors:
        return True

    url = f"{SERVICE_B_BASE_URL}/api/internal/vectors/sync"
    payload = {"vectors": vectors}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                url,
                headers=get_headers(),
                json=payload,
                timeout=60,
            )
            if response.status_code == 401:
                logger.error("Authentication failed on push. Check VECTOR_SYNC_API_TOKEN.")
                return False
            response.raise_for_status()
            result = response.json()
            logger.info(
                f"Push result: {result.get('stored', 0)} stored, "
                f"{result.get('errors', 0)} errors"
            )
            return True
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Push connection failed (attempt {attempt}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
        except requests.exceptions.Timeout:
            logger.warning(f"Push timed out (attempt {attempt}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
        except requests.exceptions.HTTPError as e:
            logger.error(f"Push HTTP error: {e}")
            return False

    logger.error("Max retries reached. Could not push vectors.")
    return False


def run_single_batch(model) -> int:
    """Run a single vectorization batch. Returns count of processed products."""
    products = fetch_products()
    if products is None:
        return -1  # Signal connection failure
    if not products:
        return 0

    vectors = generate_embeddings(model, products)
    if not vectors:
        return 0

    success = push_vectors(vectors)
    return len(vectors) if success else -1


def main():
    parser = argparse.ArgumentParser(description="AI Worker Node - Vector Generation")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument(
        "--interval", type=int, default=30,
        help="Seconds between polls in loop mode (default: 30)"
    )
    parser.add_argument(
        "--batch-size", type=int, default=BATCH_SIZE,
        help=f"Number of products per batch (default: {BATCH_SIZE})"
    )
    args = parser.parse_args()

    if not VECTOR_SYNC_API_TOKEN:
        logger.error("VECTOR_SYNC_API_TOKEN not set. Exiting.")
        sys.exit(1)

    global BATCH_SIZE
    BATCH_SIZE = args.batch_size

    # Load model once
    model = load_model()

    if args.loop:
        logger.info(f"Starting continuous polling (interval: {args.interval}s, batch: {BATCH_SIZE})")
        total_processed = 0
        consecutive_empty = 0

        while True:
            try:
                count = run_single_batch(model)
                if count > 0:
                    total_processed += count
                    consecutive_empty = 0
                    logger.info(f"Total processed this session: {total_processed}")
                    # Short pause between batches when there's work
                    time.sleep(2)
                elif count == 0:
                    consecutive_empty += 1
                    # Adaptive backoff when no work available
                    wait = min(args.interval * consecutive_empty, 300)
                    logger.info(f"No products to process. Waiting {wait}s...")
                    time.sleep(wait)
                else:
                    # Connection failure — wait and retry
                    logger.warning(f"Batch failed. Retrying in {args.interval}s...")
                    time.sleep(args.interval)
            except KeyboardInterrupt:
                logger.info(f"Stopped. Total processed: {total_processed}")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}", exc_info=True)
                time.sleep(args.interval)
    else:
        # Single run
        count = run_single_batch(model)
        if count > 0:
            logger.info(f"Successfully processed {count} products.")
        elif count == 0:
            logger.info("No products need vectorization.")
        else:
            logger.error("Batch failed.")
            sys.exit(1)


if __name__ == "__main__":
    main()
