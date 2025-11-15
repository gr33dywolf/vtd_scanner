# vtd_scanner.py
import os
import json
import time
import logging
import threading
import asyncio
from datetime import datetime
from typing import Dict, Set, List
import requests

from playwright.async_api import async_playwright

# Config
POLL_INTERVAL = 360  # seconds
SEARCH_FILE = "search.json"
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
LISTING_LIMIT_PER_NOTIFY = 10

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("vtd_scanner")

# State
seen_per_search: Dict[str, Set[str]] = {}
playwright_loop = None

DISCORD_API_BASE = "https://discord.com/api/v10"

def send_discord_message(channel_id: str, token: str, content: str, button_label: str, button_url: str):
    url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    payload = {
        "content": content,
        "components": [
            {"type": 1, "components": [{"type": 2, "style": 5, "label": button_label, "url": button_url}]}
        ],
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        if resp.status_code in (200, 201):
            logger.info(f"Notification envoyée pour {button_url}")
        else:
            logger.error(f"Erreur Discord {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.exception(f"Exception en envoyant Discord: {e}")

def load_searches() -> List[str]:
    try:
        with open(SEARCH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "searches" in data:
            return data["searches"]
        logger.error("Format search.json non attendu (attendu list ou {\"searches\": [...]})")
        return []
    except Exception as e:
        logger.exception(f"Impossible de charger {SEARCH_FILE}: {e}")
        return []

def extract_listing_id_from_href(href: str) -> str:
    # Vinted item urls contain /item/<id>... we try to parse that pattern
    try:
        parts = href.split("/item/")
        if len(parts) >= 2:
            tail = parts[1]
            # id may be followed by '-' or '/'
            id_part = tail.split("-")[0].split("/")[0]
            return id_part
    except Exception:
        pass
    return href

async def fetch_listings_with_playwright(url: str, browser) -> List[Dict]:
    page = await browser.new_page()
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        # Allow any client-side rendering
        # Query typical item anchors - adapt selectors if needed
        # Vinted uses link selectors like 'a[href*="/item/"]'
        anchors = await page.query_selector_all('a[href*="/item/"]')
        results = []
        seen_hrefs = set()
        for a in anchors:
            href = await a.get_attribute("href")
            if not href:
                continue
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            title = await a.get_attribute("title") or ""
            full_url = href if href.startswith("http") else ("https://www.vinted.fr" + href)
            item_id = extract_listing_id_from_href(full_url)
            results.append({"id": item_id, "url": full_url, "title": title})
        # De-duplicate by id preserving order
        unique = []
        ids = set()
        for r in results:
            if r["id"] not in ids:
                ids.add(r["id"])
                unique.append(r)
        return unique
    except Exception as e:
        logger.exception(f"Erreur Playwright fetching {url}: {e}")
        return []
    finally:
        try:
            await page.close()
        except Exception:
            pass

def launch_playwright_loop():
    global playwright_loop
    if playwright_loop:
        return
    playwright_loop = asyncio.new_event_loop()
    t = threading.Thread(target=playwright_loop.run_forever, daemon=True)
    t.start()

async def _worker_async(search_url: str, browser):
    if search_url not in seen_per_search:
        seen_per_search[search_url] = set()
    logger.info(f"Démarrage du worker async pour: {search_url}")
    while True:
        listings = await fetch_listings_with_playwright(search_url, browser)
        new_items = []
        for it in listings:
            if it["id"] not in seen_per_search[search_url]:
                seen_per_search[search_url].add(it["id"])
                new_items.append(it)
        if new_items:
            logger.info(f"Nouvelles annonces ({len(new_items)}) pour {search_url}")
            summary_lines = []
            for it in new_items[:LISTING_LIMIT_PER_NOTIFY]:
                title = it.get("title") or it["url"]
                summary_lines.append(f"- {title}")
            if len(new_items) > LISTING_LIMIT_PER_NOTIFY:
                summary_lines.append(f"...et {len(new_items)-LISTING_LIMIT_PER_NOTIFY} autres")
            content = f"🔔 {len(new_items)} nouvelle(s) annonce(s) pour votre recherche:\n" + "\n".join(summary_lines)
            send_discord_message(CHANNEL_ID, DISCORD_TOKEN, content, "Voir les annonces", search_url)
        else:
            logger.info(f"Aucune nouvelle annonce pour {search_url}")
        await asyncio.sleep(POLL_INTERVAL)

def start_worker_for_search(search_url: str):
    # Schedule coroutine in the playwright loop
    async def schedule():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                await _worker_async(search_url, browser)
            finally:
                try:
                    await browser.close()
                except Exception:
                    pass
    # Run schedule in global loop
    asyncio.run_coroutine_threadsafe(schedule(), playwright_loop)

def main():
    if not DISCORD_TOKEN or not CHANNEL_ID:
        logger.error("DISCORD_TOKEN ou CHANNEL_ID manquant.")
        return
    searches = load_searches()
    if not searches:
        logger.error("Aucune recherche chargée dans search.json.")
        return
    logger.info(f"{len(searches)} recherches chargées.")
    # Start Playwright event loop
    launch_playwright_loop()
    # Start a worker (separate coroutine) for each search
    for s in searches:
        start_worker_for_search(s)
        time.sleep(0.5)
    # Import keep_alive (it will start Flask server)
    try:
        import keep_alive  # starts server on import
        logger.info("keep_alive démarré.")
    except Exception:
        logger.exception("Erreur lors de l'import keep_alive.")
    # Keep main thread alive
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Arrêt demandé.")

if __name__ == "__main__":
    main()
