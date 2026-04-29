import time
import logging
import pycron
from datetime import datetime
import pytz
from config import SCHEDULER_CRON, SCHEDULER_TIMEZONE, DEFAULT_THREADS
from scraper import run_scraper, is_today_scrape_done

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def now_in_tz():
    return datetime.now(pytz.timezone(SCHEDULER_TIMEZONE))


def job():
    logger.info("Starting scheduled scrape job...")
    try:
        run_scraper(threads=DEFAULT_THREADS)
        logger.info("Scrape job finished.")
    except Exception as e:
        logger.error(f"Error during scrape job: {e}")


if __name__ == "__main__":
    logger.info("Container started. Checking today's run state...")
    if not is_today_scrape_done():
        logger.info("Today's run not found — running initial scrape...")
        job()
        logger.info("Initial scrape complete.")
    else:
        logger.info("Today's scrape already completed — skipping initial run.")

    logger.info(f"Entering scheduler loop (cron: {SCHEDULER_CRON}, tz: {SCHEDULER_TIMEZONE}).")

    while True:
        current_time = now_in_tz()
        if pycron.is_now(SCHEDULER_CRON, dt=current_time):
            if not is_today_scrape_done():
                job()
            else:
                logger.info("Scheduled run skipped — today's scrape already completed.")
            time.sleep(60)
        time.sleep(20)
