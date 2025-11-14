import os
import json
import asyncio
import logging
from datetime import datetime
import threading

import discord
from discord import Embed, Intents

from playwright.async_api import async_playwright
from keep_alive import app as keepalive_app


# ----------------- CONFIG -----------------
SEARCH_FILE = "search.json"
SEEN_FILE = "seen.json"
POLL_INTERVAL = 360   # secondes

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger("vtd_scanner")

intents = Intents.default()
client = discord.Client(intents=intents)
# -----------------------------------------


# ---------- UTILS -----------
def load_seen():
    if not os.path.exists(SEEN_FILE):
        return {}
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except:
        return {}

def save_seen(data):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_searches():
    if not os.path.exists(SEARCH_FILE):
        logger.error("search.json introuvable !")
        return []
    try:
        with open(SEARCH_FILE, "r", encoding="utf-8") as f:
            urls = json.load(f)
            logger.info(f"{len(urls)} URL(s) chargée(s) depuis search.json")
            return urls
    except Exception as e:
        logger.error(f"Erreur lecture search.json: {e}")
        return []
# ---------------------------


async def load_page_html(browser, url):
    """
    Ouvre une page par URL pour éviter que Vinted ne détecte un scraping.
    Cette fonction est appelée en parallèle pour chaque URL.
    """
    try:
        page = await browser.new_page()
        await page.goto(url, timeout=30000)
        await page.wait_for_timeout(1200)
        html = await page.content()
        await page.close()
        return url, html
    except Exception as e:
        logger.error(f"Erreur chargement {url}: {e}")
        return url, ""


def parse_listings(html):
    from bs4 import BeautifulSoup
    import re

    soup = BeautifulSoup(html, "lxml")
    items = []

    for a in soup.select('a[href*="/item/"]'):
        href = a.get("href")
        if not href:
            continue

        url = "https://www.vinted.fr" + href if href.startswith("/") else href
        item_id = url.split("/item/")[-1].split("-")[0].split("?")[0]

        if any(i["id"] == item_id for i in items):
            continue

        title = a.get("title") or a.get("aria-label") or "Annonce Vinted"

        # extraction prix
        price = ""
        text = a.get_text(" ", strip=True)
        m = re.search(r"\d+\s?€", text)
        if m:
            price = m.group(0)

        img_url = ""
        img = a.find("img")
        if img:
            img_url = img.get("src") or img.get("data-src") or ""

        items.append({
            "id": item_id,
            "title": title,
            "url": url,
            "price": price,
            "images": [img_url] if img_url else []
        })

    return items


async def scan_and_report(browser, channel, searches, seen):
    logger.info("Chargement des pages en parallèle…")

    # ---- PARALLÈLE ----
    results = await asyncio.gather(
        *(load_page_html(browser, url) for url in searches)
    )
    # -------------------

    new_total = 0

    for url, html in results:
        if not html:
            logger.warning(f"Page vide pour {url}")
            continue

        listings = parse_listings(html)

        for item in listings:
            if item["id"] in seen:
                continue

            embed = Embed(
                title=item["title"],
                url=item["url"],
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Prix", value=item["price"] or "ND", inline=True)

            if item["images"]:
                embed.set_image(url=item["images"][0])

            embed.set_footer(text="Scanner Vinted – Playwright FAST")

            try:
                await channel.send(embed=embed)
                logger.info(f"Nouvelle annonce envoyée : {item['id']}")
            except Exception as e:
                logger.error(f"Erreur Discord: {e}")

            seen[item["id"]] = {
                "url": item["url"],
                "first_seen": datetime.utcnow().isoformat()
            }
            new_total += 1

    if new_total > 0:
        save_seen(seen)

    logger.info(f"Scan terminé : {new_total} nouvelles annonces.")


@client.event
async def on_ready():
    logger.info(f"Bot connecté : {client.user}")

    channel = client.get_channel(CHANNEL_ID)
    if not channel:
        logger.error(f"Salon Discord {CHANNEL_ID} introuvable.")
        return

    searches = load_searches()
    if not searches:
        logger.error("Aucune URL dans search.json !")
        return

    seen = load_seen()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)

        while True:
            logger.info("Début d’un cycle de scan…")
            await scan_and_report(browser, channel, searches, seen)
            logger.info(f"Pause {POLL_INTERVAL}s…")
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
