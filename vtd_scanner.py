# vtd_scanner.py
"""
Bot Vinted -> Discord
- Scan les URLs de recherche Vinted toutes les 360s
- Gère mieux les 403 en cas de blocage serveur
- Utilise headers plus “browser-like”
- Intègre keep_alive Flask + Thread
- Logs horodatés
"""

import os
import asyncio
import json
import logging
import threading
import time
from datetime import datetime
from typing import List, Dict, Any

import aiohttp
from aiohttp import ClientSession
from bs4 import BeautifulSoup
import discord

from keep_alive import app as keepalive_app

SEARCH_FILE = 'search.json'
SEEN_FILE = 'seen.json'
POLL_INTERVAL = 360  # secondes

DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN')
CHANNEL_ID = int(os.environ.get('CHANNEL_ID', '0'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('vtd_scanner')

intents = discord.Intents.default()
client = discord.Client(intents=intents)


def load_seen() -> Dict[str, Any]:
    if not os.path.exists(SEEN_FILE):
        logger.warning("seen.json n’existe pas — création d’un nouvel objet vide.")
        return {}
    try:
        with open(SEEN_FILE, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                logger.warning("seen.json vide — réinitialisation.")
                return {}
            return json.loads(content)
    except Exception as e:
        logger.error(f"Erreur lecture seen.json (corrompu?) — réinitialisation. {e}")
        return {}


def save_seen(data: Dict[str, Any]):
    try:
        with open(SEEN_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Impossible d’écrire dans seen.json: {e}")


def load_searches() -> List[str]:
    if not os.path.exists(SEARCH_FILE):
        logger.warning("search.json introuvable.")
        return []
    try:
        with open(SEARCH_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Erreur lecture de search.json: {e}")
        return []


async def fetch(session: ClientSession, url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.vinted.fr/",
        "Connection": "keep-alive"
    }
    try:
        async with session.get(url, headers=headers, timeout=30) as resp:
            if resp.status == 403:
                logger.error(f"Erreur 403 Forbidden pour {url}")
                return ""
            resp.raise_for_status()
            text = await resp.text()
            return text
    except Exception as e:
        logger.error(f"Erreur fetch {url}: {e}")
        return ""


def parse_listings_from_search(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    results: List[Dict[str, Any]] = []

    for a in soup.select('a[href*="/item/"]'):
        href = a.get("href")
        if not href:
            continue
        if href.startswith("/"):
            url = "https://www.vinted.fr" + href
        else:
            url = href
        item_id = url.split("/item/")[-1].split("-")[0].split("?")[0]
        if any(r["id"] == item_id for r in results):
            continue
        title = a.get("title") or a.get("aria-label") or "Annonce Vinted"
        price = ""
        parent = a
        for _ in range(3):
            if parent is None:
                break
            text = parent.get_text(" ", strip=True)
            import re
            m = re.search(r"\d+\s?€", text)
            if m and not price:
                price = m.group(0)
            parent = parent.parent
        img_url = ""
        img = a.find("img")
        if img:
            img_url = img.get("src") or img.get("data-src") or ""
        results.append({
            "id": item_id,
            "title": title,
            "url": url,
            "price": price,
            "seller": "ND",
            "condition": "ND",
            "posted": "ND",
            "images": [img_url] if img_url else []
        })
    return results


async def scan_and_report(session: ClientSession, channel: discord.TextChannel, searches: List[str], seen: Dict[str, Any]):
    htmls = await asyncio.gather(*(fetch(session, url) for url in searches))

    new_total = 0
    for url, html in zip(searches, htmls):
        if not html:
            logger.info(f"Pas de contenu pour {url} — skipping.")
            continue
        listings = parse_listings_from_search(html)
        new_count = 0
        for item in listings:
            if item["id"] in seen:
                continue
            embed = discord.Embed(
                title=item["title"],
                url=item["url"],
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Prix", value=item["price"] or "ND", inline=True)
            embed.add_field(name="Vendeur", value=item["seller"], inline=True)
            embed.add_field(name="État", value=item["condition"], inline=True)
            embed.add_field(name="Publié", value=item["posted"], inline=True)
            if item["images"]:
                embed.set_image(url=item["images"][0])
            embed.set_footer(text="Vinted • Scanner automatique")
            try:
                await channel.send(embed=embed)
                logger.info(f"Nouvelle annonce envoyée : {item['id']} ({item['url']})")
            except Exception as e:
                logger.error(f"Erreur envoi Discord pour {item['id']}: {e}")
            seen[item["id"]] = {"url": item["url"], "first_seen": datetime.utcnow().isoformat()}
            new_total += 1
            new_count += 1
        if new_count > 0:
            logger.info(f"{new_count} nouvelles annonces trouvées pour {url}")
    if new_total > 0:
        save_seen(seen)
    logger.info(f"Scan terminé — {new_total} nouvelles annonces.")

@client.event
async def on_ready():
    logger.info(f"Bot connecté : {client.user}")
    channel = client.get_channel(CHANNEL_ID)
    if not channel:
        logger.error(f"Salon avec ID {CHANNEL_ID} introuvable.")
        return
    searches = load_searches()
    if not searches:
        logger.warning("Aucune URL de recherche chargée.")
        return
    seen = load_seen()
    async with aiohttp.ClientSession() as session:
        while True:
            logger.info("Début d’un cycle de recherche…")
            await scan_and_report(session, channel, searches, seen)
            logger.info(f"Pause {POLL_INTERVAL} secondes avant le prochain cycle.")
            await asyncio.sleep(POLL_INTERVAL)

def run_keep_alive():
    keepalive_app.run(host="0.0.0.0", port=8080)

def main():
    if not DISCORD_TOKEN or CHANNEL_ID == 0:
        logger.error("DISCORD_TOKEN ou CHANNEL_ID manquant.")
        return
    threading.Thread(target=run_keep_alive, daemon=True).start()
    client.run(DISCORD_TOKEN)

if __name__ == "__main__":
    main()
