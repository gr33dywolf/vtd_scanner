#!/usr/bin/env python3
"""
vtd_scanner.py

Lance un scanner asynchrone qui exécute toutes les recherches listées dans search.json
chaque 360 secondes (6 minutes), en parallèle.
Envoie une notification dans Discord (channel indiqué par CHANNEL_ID) via l'API HTTP de Discord
avec un bouton "Voir les annonces" pointant sur l'URL de la recherche.

Configuration attendue (dans les variables d'environnement de Render):
- DISCORD_TOKEN
- CHANNEL_ID
- PROXY_URL (optionnel) : si Vinted bloque, vous pouvez définir un proxy HTTP(S) ou SOCKS

Le script conserve un fichier `seen.json` pour éviter les doublons.
"""

import os
import sys
import json
import asyncio
import logging
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
import subprocess

import aiohttp

# Config
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
SEARCH_FILE = os.getenv("SEARCH_FILE", "search.json")
SEEN_FILE = os.getenv("SEEN_FILE", "seen.json")
INTERVAL = int(os.getenv("INTERVAL_SECONDS", "360"))  # 360s par défaut
PROXY_URL = os.getenv("PROXY_URL")  # optionnel

if not DISCORD_TOKEN or not CHANNEL_ID:
    print("[ERROR] DISCORD_TOKEN et CHANNEL_ID doivent être définis dans les variables d'environnement.")
    sys.exit(1)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Helpers pour persister les annonces vues
def load_json_file(path: str, default: Any):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:
        logger.warning(f"Impossible de charger {path}: {e}")
        return default


def save_json_file(path: str, data: Any):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Impossible d'enregistrer {path}: {e}")


# Charge les URLs de recherche
def load_search_urls(path: str) -> List[str]:
    data = load_json_file(path, [])
    if not isinstance(data, list):
        logger.error(f"{path} doit contenir une liste d'URLs.")
        return []
    return data


# Création d'en-têtes robustes pour éviter les 403
def default_headers(referer: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, text/html, application/xhtml+xml, */*;q=0.01",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "X-Requested-With": "XMLHttpRequest",
    }
    if referer:
        headers["Referer"] = referer
    return headers


async def fetch_search(session: aiohttp.ClientSession, url: str) -> Dict[str, Any]:
    """Récupère une recherche. Essaie d'interpréter JSON si possible, sinon renvoie HTML brut."""
    try:
        async with session.get(url, headers=default_headers(referer=url), proxy=PROXY_URL, timeout=30) as resp:
            text = await resp.text()
            ctype = resp.headers.get("Content-Type", "")
            if "application/json" in ctype or text.strip().startswith("{") or text.strip().startswith("["):
                try:
                    return {"status": resp.status, "json": await resp.json()}
                except Exception:
                    # fallback: return text in payload
                    return {"status": resp.status, "text": text}
            else:
                return {"status": resp.status, "text": text}
    except Exception as e:
        logger.error(f"Erreur lors de la requête vers {url}: {e}")
        return {"status": None, "error": str(e)}


def extract_items_from_response(url: str, resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Tentative générique d'extraction d'annonces depuis la réponse.
    On recherche des identifiants uniques (id) ou des slugs/url.
    Cette fonction peut être adaptée selon la structure réelle des réponses Vinted que vous utilisez.
    """
    items = []
    if resp.get("json"):
        j = resp["json"]
        # Cas fréquent: catalogue d'items
        # On tente plusieurs chemins communs
        candidates = []
        if isinstance(j, dict):
            # exemples: j.get('items') ou j.get('catalog_items')
            for key in ("items", "catalog_items", "items_publication", "search_results"):
                if key in j and isinstance(j[key], list):
                    candidates = j[key]
                    break
            # sinon si l'objet contient directement des 'id's
            if not candidates:
                # parcours récursif bref
                def find_lists(o):
                    res = []
                    if isinstance(o, dict):
                        for v in o.values():
                            res += find_lists(v)
                    elif isinstance(o, list):
                        res.append(o)
                    return res
                lists = find_lists(j)
                for l in lists:
                    if l and isinstance(l[0], dict) and ("id" in l[0] or "title" in l[0] or "url" in l[0]):
                        candidates = l
                        break
        elif isinstance(j, list):
            candidates = j

        for it in candidates:
            if not isinstance(it, dict):
                continue
            # essaye de récupérer id et url
            item_id = None
            item_url = None
            for key in ("id", "item_id", "thread_id"):
                if key in it:
                    item_id = str(it[key])
                    break
            for key in ("url", "title", "url_title", "canonical_url"):
                if key in it:
                    item_url = it[key]
                    break
            # parfois l'url doit être construite
            if not item_url:
                # exemple: user + id
                if item_id:
                    item_url = f"https://www.vinted.fr/item/show/{item_id}"
            if item_id or item_url:
                items.append({"id": item_id or item_url, "url": item_url or "", "raw": it})
    elif resp.get("text"):
        # Pas de JSON — très basique: tenter extraire des href vers /item/
        import re
        text = resp["text"]
        found = set(re.findall(r"https?://[^"]+/item/(?:show/)?(\d+)", text))
        for fid in found:
            items.append({"id": fid, "url": f"https://www.vinted.fr/item/show/{fid}", "raw": {}})
    return items


async def send_discord_notification(session: aiohttp.ClientSession, channel_id: str, search_url: str, new_items: List[Dict[str, Any]]):
    """Envoie une notification au channel Discord via l'API.
    Ajoute un bouton "Voir les annonces" pointant vers la search_url.
    """
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {DISCORD_TOKEN}",
        "Content-Type": "application/json",
    }

    # Construire un embed résumé
    embeds = []
    if new_items:
        description_lines = []
        # on limite le nombre d'items listés dans l'embed
        for it in new_items[:6]:
            desc = f"[{it.get('id')}]({it.get('url')})" if it.get('url') else f"{it.get('id')}"
            description_lines.append(desc)
        embed = {
            "title": "Nouvelles annonces trouvées",
            "description": "\n".join(description_lines),
            "timestamp": datetime.utcnow().isoformat(),
        }
        embeds.append(embed)

    payload = {
        "content": f"🔔 Nouvelles annonces pour la recherche: {search_url}",
        "embeds": embeds,
        "components": [
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 5,  # Link button
                        "label": "Voir les annonces",
                        "url": search_url,
                    }
                ]
            }
        ]
    }

    try:
        async with session.post(url, json=payload, headers=headers, timeout=15) as resp:
            if resp.status in (200, 201):
                logger.info(f"Notification envoyée pour {search_url} (items: {len(new_items)})")
            else:
                text = await resp.text()
                logger.error(f"Erreur en envoyant la notification Discord: {resp.status} {text}")
    except Exception as e:
        logger.error(f"Erreur HTTP lors de l'envoi Discord: {e}")


async def process_search(session: aiohttp.ClientSession, url: str, seen: Dict[str, List[str]]) -> None:
    resp = await fetch_search(session, url)
    items = extract_items_from_response(url, resp)
    logger.info(f"{len(items)} annonces potentielles extraites pour {url}")

    seen_for_url = set(seen.get(url, []))
    new = []
    for it in items:
        ident = it.get("id") or it.get("url")
        if not ident:
            continue
        if ident not in seen_for_url:
            new.append(it)
            seen_for_url.add(ident)

    if new:
        # enregistrer immédiatement
        seen[url] = list(seen_for_url)
        save_json_file(SEEN_FILE, seen)
        await send_discord_notification(session, CHANNEL_ID, url, new)
        logger.info(f"{len(new)} nouvelles annonces pour {url}")
    else:
        logger.info(f"Pas de nouvelles annonces pour {url}")


async def main_loop():
    # Démarrage du keep-alive (lance keep_alive.py en sous-processus)
    try:
        logger.info("Démarrage du keep_alive.py en arrière-plan...")
        subprocess.Popen([sys.executable, "keep_alive.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        logger.warning(f"Impossible de démarrer keep_alive.py automatiquement: {e}")

    search_urls = load_search_urls(SEARCH_FILE)
    if not search_urls:
        logger.error("Aucune URL de recherche trouvée — remplissez search.json et redémarrez.")
        return

    seen = load_json_file(SEEN_FILE, {})

    async with aiohttp.ClientSession() as session:
        while True:
            start = time.time()
            logger.info(f"Lancement des {len(search_urls)} recherches simultanées")
            tasks = [process_search(session, url, seen) for url in search_urls]
            await asyncio.gather(*tasks)
            elapsed = time.time() - start
            logger.info(f"Cycle terminé en {elapsed:.2f}s — prochaine exécution dans {INTERVAL}s")
            await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("Arrêt demandé")
