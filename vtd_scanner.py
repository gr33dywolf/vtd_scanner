# vtd_scanner.py
import os
import time
import json
import logging
import threading
import requests
from datetime import datetime
from typing import Dict, Set, List
from urllib.parse import urlparse, parse_qs

# Config
POLL_INTERVAL = 360  # secondes
SEARCH_FILE = "search.json"
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

# Discord webhook via Bot API (send message with button using components)
DISCORD_API_BASE = "https://discord.com/api/v10"

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("vtd_scanner")

# Keep track of seen listing IDs per search URL
seen_per_search: Dict[str, Set[str]] = {}

# Helper: send message with button to channel
def send_discord_message(channel_id: str, token: str, content: str, button_label: str, button_url: str):
    url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json"
    }
    # Discord message payload with a button (message components)
    payload = {
        "content": content,
        "components": [
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 5,
                        "label": button_label,
                        "url": button_url
                    }
                ]
            }
        ]
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        if resp.status_code in (200, 201):
            logger.info(f"Notification envoyée pour URL: {button_url}")
        else:
            logger.error(f"Erreur en envoyant Discord ({resp.status_code}): {resp.text}")
    except Exception as e:
        logger.exception(f"Exception en envoyant Discord: {e}")

# Helper: load searches
def load_searches() -> List[str]:
    try:
        with open(SEARCH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and "searches" in data:
            return data["searches"]
        else:
            logger.error("search.json format non attendu. Attendu: list ou {\"searches\": [...]}")
            return []
    except FileNotFoundError:
        logger.error(f"{SEARCH_FILE} introuvable.")
        return []
    except Exception as e:
        logger.exception(f"Erreur en lisant {SEARCH_FILE}: {e}")
        return []

# Helper: parse listing id from an item's URL or dict (adapt selon source)
def extract_id_from_listing(listing: Dict) -> str:
    # If listing already has an 'id' field
    if isinstance(listing, dict):
        if "id" in listing:
            return str(listing["id"])
        if "item_id" in listing:
            return str(listing["item_id"])
        if "url" in listing:
            # try to extract last path segment
            try:
                path = urlparse(listing["url"]).path
                return path.rstrip("/").split("/")[-1]
            except Exception:
                pass
    # Fallback
    return str(listing)

# Function to fetch results for a given search URL
def fetch_search_results(search_url: str) -> List[Dict]:
    """
    NOTE: Vinted blocks some direct API calls with 403. This function uses a lightweight request with
    browser-like headers. Adjust parsing according to the actual response format. If you have a working
    non-HTTPS source or custom proxy, replace logic here.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.vinted.fr/",
    }
    try:
        resp = requests.get(search_url, headers=headers, timeout=20)
        if resp.status_code == 200:
            # Try JSON first
            try:
                data = resp.json()
                # If response is an object with "items" or "items" key, adapt accordingly
                if isinstance(data, dict):
                    # common Vinted API wrappers might use "items", "search_items", "items_html", etc.
                    if "items" in data and isinstance(data["items"], list):
                        return data["items"]
                    if "search_items" in data and isinstance(data["search_items"], list):
                        return data["search_items"]
                    # If structure unknown, return empty and let user adapt
                    logger.debug("Réponse JSON reçue mais structure non reconnue.")
                    return []
                elif isinstance(data, list):
                    return data
            except ValueError:
                # Not JSON — try to parse HTML to discover item URLs (very basic)
                html = resp.text
                # Simple heuristic: find occurrences of item links like /item/12345678-...
                results = []
                # This is a naive approach: search for "/item/" occurrences
                marker = "/item/"
                idx = 0
                found_ids = set()
                while True:
                    idx = html.find(marker, idx)
                    if idx == -1:
                        break
                    start = idx + len(marker)
                    # read until next quote or slash
                    end = start
                    while end < len(html) and html[end] not in ['"', "'", " ", "<", ">"]:
                        end += 1
                    candidate = html[start:end].split("/")[0]
                    if candidate and candidate not in found_ids:
                        found_ids.add(candidate)
                        results.append({"url": f"https://www.vinted.fr/item/{candidate}", "id": candidate})
                    idx = end
                return results
        else:
            logger.warning(f"Requête vers {search_url} renvoyée {resp.status_code}")
    except Exception as e:
        logger.exception(f"Erreur fetch_search_results pour {search_url}: {e}")
    return []

# Worker for a single search
def worker_search(search_url: str):
    if search_url not in seen_per_search:
        seen_per_search[search_url] = set()
    logger.info(f"Démarrage du worker pour: {search_url}")
    while True:
        results = fetch_search_results(search_url)
        new_items = []
        for item in results:
            item_id = extract_id_from_listing(item)
            if item_id not in seen_per_search[search_url]:
                seen_per_search[search_url].add(item_id)
                new_items.append(item)
        if new_items:
            logger.info(f"Nouvelles annonces trouvées pour {search_url} : {len(new_items)}")
            # Send a single Discord notification summarizing new items, with a button to "Voir les annonces"
            # Build a summary
            summary_lines = []
            for it in new_items[:10]:
                # try to extract title and url if present
                title = it.get("title") if isinstance(it, dict) else None
                url = it.get("url") if isinstance(it, dict) else None
                if not url:
                    # fallback: use the search URL as link for button; direct item links may be built from id
                    url = it.get("url") if isinstance(it, dict) and "url" in it else search_url
                if title:
                    summary_lines.append(f"- {title}")
                else:
                    summary_lines.append(f"- {url}")
            if len(new_items) > 10:
                summary_lines.append(f"...et {len(new_items)-10} autres")
            content = f"🔔 {len(new_items)} nouvelle(s) annonce(s) pour la recherche:\n" + "\n".join(summary_lines)
            # Use the search URL as the button link
            send_discord_message(CHANNEL_ID, DISCORD_TOKEN, content, "Voir les annonces", search_url)
        else:
            logger.info(f"Aucune nouvelle annonce pour {search_url}")
        # Sleep until next poll
        time.sleep(POLL_INTERVAL)

def main():
    if not DISCORD_TOKEN or not CHANNEL_ID:
        logger.error("DISCORD_TOKEN ou CHANNEL_ID manquant dans les variables d'environnement.")
        return
    searches = load_searches()
    if not searches:
        logger.error("Aucune recherche chargée. Veuillez renseigner search.json.")
        return
    logger.info(f"{len(searches)} recherches chargées.")
    # Start workers for all searches in parallel threads
    threads = []
    for s in searches:
        t = threading.Thread(target=worker_search, args=(s,), daemon=True)
        t.start()
        threads.append(t)
        # small stagger to avoid thundering herd
        time.sleep(0.5)
    # Also start keep_alive server in separate module
    try:
        import keep_alive  # keep_alive.py should start Flask app in its own thread
        logger.info("keep_alive importé.")
    except Exception as e:
        logger.exception(f"Erreur en important keep_alive: {e}")
    # Keep main thread alive indefinitely with logging
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Arrêt demandé (KeyboardInterrupt).")

if __name__ == "__main__":
    main()
