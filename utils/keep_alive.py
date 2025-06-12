import os
import time
import requests
import threading
import logging

logger = logging.getLogger(__name__)

def keep_alive():
    url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/"
    def ping():
        while True:
            try:
                response = requests.get(url)
                logger.info(f"[AUTOPING] {url} — {response.status_code}")
            except Exception as e:
                logger.warning(f"[AUTOPING] Error: {e}")
            time.sleep(600)
    threading.Thread(target=ping, daemon=True).start()
