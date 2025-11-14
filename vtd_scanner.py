# vtd_scanner.py
"""
Bot Vinted -> Discord
- Scan toutes les URLs depuis search.json toutes les 360s
- Envoi sur Discord avec embed : titre, prix, vendeur, état, date, image, lien
- Logs horodatés dans Render
- Stocke les annonces déjà envoyées dans seen.json
"""

import os
import asyncio
import json
import logging
from datetime import datetime
from typing import List, Dict, Any

import aiohttp
from aiohttp import ClientSession
from bs4 import BeautifulSoup
import discord

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


async def fetch(session: ClientSession, url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        async with session.get(url, headers=headers, timeout=30) as resp:
            resp.raise_for_status()
            return await resp.text()
    except Exception as e:
        logger.error(f"Erreur fetch {url}: {e}")
        return ""


def load_searches() -> List[str]:
    if not os.path.exists(SEARCH_FILE):
        logger.warning("search.json introuvable.")
        return []
    with open(SEARCH_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_seen() -> Dict[str, Any]:
    if not os.path.exists(SEEN_FILE):
        return {}
    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_seen(data: Dict[str, Any]):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_listings_from_search(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    results = []

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
        img_url = ""

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

            embed.set_footer(text="Vinted • Recherche")

            try:
                await channel.send(embed=embed)
                logger.info(f"Nouvelle annonce envoyée : {item['id']} ({item['url']})")
            except Exception as e:
                logger.error(f"Erreur envoi Discord : {e}")

            seen[item["id"]] = {"url": item["url"], "first_seen": datetime.utcnow().isoformat()}
            new_total += 1
            new_count += 1

        if new_count > 0:
            logger.info(f"{new_count} nouvelles annonces trouvées pour {url}")

    if new_total > 0:
        save_seen(seen)

    logger.info(f"Scan terminé — {new_total} annonces nouvelles au total.")


@client.event
async def on_ready():
    logger.info(f"Bot connecté : {client.user}")

    channel = client.get_channel(CHANNEL_ID)
    if not channel:
        logger.error("CHANNEL_ID introuvable ou bot sans accès.")
        return

    searches = load_searches()
    if not searches:
        logger.warning("Aucune recherche dans search.json")
        return

    seen = load_seen()

    async with aiohttp.ClientSession() as session:
        while True:
            logger.info("Début d’un cycle de recherche…")
            await scan_and_report(session, channel, searches, seen)
            logger.info(f"Pause {POLL_INTERVAL}s …")
            await asyncio.sleep(POLL_INTERVAL)


def main():
    if not DISCORD_TOKEN or CHANNEL_ID == 0:
        logger.error("Variables d'environnement DISCORD_TOKEN et CHANNEL_ID manquantes.")
        return
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
