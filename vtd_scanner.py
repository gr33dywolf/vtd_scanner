import discord
from discord.ext import tasks
import requests
from bs4 import BeautifulSoup
import json
import os

# Variables d'environnement
TOKEN = os.getenv("TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

# Intents Discord
intents = discord.Intents.default()
client = discord.Client(intents=intents)

# Chargement des recherches
with open("recherches.json", "r", encoding="utf-8") as f:
    RECHERCHES = json.load(f)

# Suivi des annonces déjà envoyées
derniers_ids = {r['nom']: set() for r in RECHERCHES}


def scrape_vinted(url):
    """Récupère les annonces depuis l'URL de recherche Vinted"""
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(r.text, "html.parser")
    return soup.find_all("div", {"class": "feed__item"})


def get_new_items():
    """Retourne les nouvelles annonces avec lien, prix et image"""
    nouvelles = []

    for recherche in RECHERCHES:
        nom = recherche["nom"]
        url = recherche["url"]

        annonces = scrape_vinted(url)

        for a in annonces:
            item_id = a.get("data-id")
            if item_id and item_id not in derniers_ids[nom]:
                derniers_ids[nom].add(item_id)

                # Lien de l'annonce
                link_tag = a.find("a")
                link = "https://www.vinted.fr" + link_tag.get("href") if link_tag else "Lien non disponible"

                # Prix
                price_tag = a.find("div", class_="feed__item-price")
                price = price_tag.text.strip() if price_tag else "Prix inconnu"

                # Image
                img_tag = a.find("img")
                img_url = img_tag["src"] if img_tag else None

                nouvelles.append((nom, link, price, img_url))

    return nouvelles


@client.event
async def on_ready():
    print(f"{client.user} connecté !")
    scan.start()


@tasks.loop(seconds=180)  # Vérifie toutes les 180 secondes
async def scan():
    channel = client.get_channel(CHANNEL_ID)
    nouvelles = get_new_items()

    for nom, url, price, img_url in nouvelles:
        embed = discord.Embed(
            title=nom,
            url=url,
            description=f"Prix : {price}",
            color=0x1abc9c
        )
        if img_url:
            embed.set_image(url=img_url)

        await channel.send(embed=embed)


client.run(TOKEN)

