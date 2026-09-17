import os
import sys
import logging
from dotenv import load_dotenv
from mongo_auth import service_uri


# Load environment variables from .env (simple, explicit)
load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data directory resolution: env var → virtualenv fallback → error
# ---------------------------------------------------------------------------
DATA_FOLDER_ENV = os.getenv('DATA_FOLDER', '/app/data')
if DATA_FOLDER_ENV:
    DATA_DIR = os.path.abspath(DATA_FOLDER_ENV)
else:
    venv_path = os.getenv('VIRTUAL_ENV') or (
        sys.prefix if getattr(sys, 'base_prefix', sys.prefix) != sys.prefix else None
    )
    if venv_path:
        DATA_DIR = os.path.abspath(os.path.join(venv_path, 'data'))
    else:
        print("Error: no DATA_FOLDER env var set and no virtualenv detected. "
              "Please set DATA_FOLDER to a valid path.")
        sys.exit(1)
# ---------------------------------------------------------------------------
# MongoDB setup
# ---------------------------------------------------------------------------
MONGO_URI = service_uri(os.getenv('MONGO_URI', 'mongodb://localhost:27017/'))
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'tesco_tracker')
MONGO_COLLECTION = os.getenv('MONGO_COLLECTION', 'products')
# ---------------------------------------------------------------------------
# Scraper / threading defaults
# ---------------------------------------------------------------------------
DEFAULT_THREADS = 2

# ---------------------------------------------------------------------------
# Scheduler settings
# ---------------------------------------------------------------------------
SCHEDULER_CRON = '0 5 * * *'
SCHEDULER_TIMEZONE = 'Europe/Budapest'
SCHEDULER_RETRY_INITIAL_SECONDS = max(
    1, int(os.getenv('SCHEDULER_RETRY_INITIAL_SECONDS', '1800'))
)
SCHEDULER_RETRY_MAX_SECONDS = max(
    SCHEDULER_RETRY_INITIAL_SECONDS,
    int(os.getenv('SCHEDULER_RETRY_MAX_SECONDS', '7200')),
)
SCHEDULER_MAX_RETRIES_PER_DAY = max(
    0, int(os.getenv('SCHEDULER_MAX_RETRIES_PER_DAY', '6'))
)
SCHEDULER_RETRY_CUTOFF_HOUR = min(
    23, max(0, int(os.getenv('SCHEDULER_RETRY_CUTOFF_HOUR', '23')))
)
# Touched by the scheduler loop on every iteration and read by the container
# health check, which runs as a separate process.
SCHEDULER_HEARTBEAT_FILE = os.getenv('SCHEDULER_HEARTBEAT_FILE', '/tmp/tesco-scheduler-heartbeat')

# ---------------------------------------------------------------------------
# Tesco API
# ---------------------------------------------------------------------------
API_URL = 'https://xapi.tesco.com/v1/graphql'
API_KEY = os.getenv('API_KEY')

if API_KEY:
    # Never log any part of the key: log lines are shipped to ClickHouse.
    logger.info("Tesco API key loaded.")
else:
    logger.warning("WARNING: API_KEY not found in environment variables or .env file!")

HEADERS = {
    'Accept': 'application/json',
    'content-type': 'application/json',
    'region': 'HU',
    'language': 'hu-HU',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

if API_KEY:
    HEADERS['x-apikey'] = API_KEY

SITEMAP_INDEX_URL = 'https://bevasarlas.tesco.hu/sitemaps/hu-HU/groceries/products-index.xml'
