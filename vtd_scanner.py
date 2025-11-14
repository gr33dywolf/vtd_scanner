import discord
from discord.ext import tasks
import requests
from bs4 import BeautifulSoup
import json
import os

TOKEN = os.getenv("TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

intents = discord.Intents.default()
client = discord.Client(intents=intents)

with open("search.json", "r", encoding="utf-8") as f:
    RECHERCHES = json.load(f)

derniers_ids = {r['nom']: set() for r in RECHERCHES}


def scrape_vinted(url):
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(r.text, "html.parser")
    return soup.find_all("div", {"class": "feed__item"})


def get_new_items():
    nouvelles = []

    for recherche in RECHERCHES:
        nom = recherche["nom"]
        url = recherche["url"]

        annonces = scrape_vinted(url)

        for a in annonces:
            item_id = a.get("data-id")
            if item_id and item_id not in derniers_ids[nom]:
                derniers_ids[nom].add(item_id)
                link = "https://www.vinted.fr" + a.find("a").get("href")
                nouvelles.append((nom, link))

    return nouvelles


@client.event
async def on_ready():
    print(f"{client.user} connecté !")
    scan.start()


@tasks.loop(seconds=60)
async def scan():
    channel = client.get_channel(CHANNEL_ID)
    nouvelles = get_new_items()

    for nom, url in nouvelles:
        await channel.send(f"🆕 **{nom}** : {url}")


client.run(TOKEN)

