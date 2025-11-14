import os
import json
import requests
from bs4 import BeautifulSoup
import discord
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
import hashlib

# Configuration du logging
def setup_logging():
    logger = logging.getLogger('VintedBot')

    # Supprimer les gestionnaires existants pour éviter les doublons
    if logger.hasHandlers():
        logger.handlers.clear()

    logger.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s: %(message)s', 
                                  datefmt='%Y-%m-%d %H:%M:%S')

    # Un seul gestionnaire de console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


class VintedBot:
    def __init__(self, discord_token, channel_id):
        # Configuration du logging
        self.logger = setup_logging()
        
        # Initialisation des paramètres du bot
        self.discord_token = discord_token
        self.channel_id = channel_id
        
        # Configuration du client Discord
        intents = discord.Intents.default()
        self.client = discord.Client(intents=intents)
        
        # Suivi des articles déjà traités
        self.last_checked_items = set()

    def generate_item_hash(self, item):
        """Générer un hash unique pour chaque article"""
        hash_input = f"{item.get('link', '')}{item.get('title', '')}{item.get('price', '')}"
        return hashlib.md5(hash_input.encode()).hexdigest()

    def scrape_vinted(self, search_url):
        """Scraper les annonces Vinted"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        try:
            self.logger.info(f"Recherche en cours sur l'URL : {search_url}")
            
            response = requests.get(search_url, headers=headers)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Sélecteurs CSS à ajuster selon la structure actuelle de Vinted
            items_containers = soup.find_all('div', class_='item-container')
            
            items = []
            for container in items_containers:
                try:
                    # Extraction des détails (à ajuster selon la structure HTML réelle)
                    item = {
                        'title': container.find('h3', class_='item-title').text.strip() if container.find('h3', class_='item-title') else 'Titre non disponible',
                        'price': container.find('span', class_='price').text.strip() if container.find('span', class_='price') else 'Prix non disponible',
                        'link': container.find('a', class_='item-link')['href'] if container.find('a', class_='item-link') else '',
                        'seller': container.find('span', class_='username').text.strip() if container.find('span', class_='username') else 'Vendeur inconnu',
                        'condition': container.find('span', class_='item-condition').text.strip() if container.find('span', class_='item-condition') else 'État non spécifié',
                        'images': [img['src'] for img in container.find_all('img', class_='item-image')[:1]] if container.find_all('img', class_='item-image') else []
                    }
                    items.append(item)
                except Exception as e:
                    self.logger.warning(f"Erreur lors du traitement d'un article : {e}")
            
            self.logger.info(f"Nombre d'articles trouvés : {len(items)}")
            return items
        
        except Exception as e:
            self.logger.error(f"Erreur lors de la récupération des données : {e}")
            return []

    async def send_discord_message(self, channel, item):
        """Envoyer un message Discord pour un article"""
        try:
            embed = discord.Embed(
                title=item['title'], 
                description=f"**Vendeur:** {item['seller']}\n**Prix:** {item['price']}\n**État:** {item['condition']}",
                color=discord.Color.green(),
                url=item['link']
            )
            
            # Ajouter la première image si disponible
            if item['images']:
                embed.set_image(url=item['images'][0])
            
            # Bouton "Acheter"
            embed.add_field(name="Lien de l'annonce", value=f"[Acheter]({item['link']})", inline=False)
            
            await channel.send(embed=embed)
            self.logger.info(f"Message envoyé pour l'article : {item['title']}")
        
        except Exception as e:
            self.logger.error(f"Erreur lors de l'envoi du message Discord : {e}")

    async def monitor_vinted(self):
        """Surveiller les recherches Vinted"""
        # Charger les configurations de recherche
        try:
            with open('search.json', 'r', encoding='utf-8') as f:
                searches = json.load(f)
        except Exception as e:
            self.logger.error(f"Erreur de lecture du fichier search.json : {e}")
            return
        
        # Récupérer le canal Discord
        try:
            channel = self.client.get_channel(int(self.channel_id))
            if not channel:
                self.logger.error("Impossible de trouver le canal Discord")
                return
        except Exception as e:
            self.logger.error(f"Erreur lors de la récupération du canal : {e}")
            return
        
        # Boucle principale de monitoring
        while True:
            for search in searches:
                try:
                    # Récupérer les articles
                    items = self.scrape_vinted(search['search_url'])
                    
                    # Traiter chaque article
                    for item in items:
                        # Générer un hash unique pour l'article
                        item_hash = self.generate_item_hash(item)
                        
                        # Vérifier si l'article n'a pas déjà été traité
                        if item_hash not in self.last_checked_items:
                            await self.send_discord_message(channel, item)
                            self.last_checked_items.add(item_hash)
                    
                    # Limiter la taille de last_checked_items
                    if len(self.last_checked_items) > 200:
                        self.last_checked_items = set(list(self.last_checked_items)[-200:])
                    
                    # Attendre avant la prochaine vérification
                    interval = search.get('check_interval', 900)
                    self.logger.info(f"Attente de {interval} secondes avant la prochaine recherche")
                    await asyncio.sleep(interval)
                
                except Exception as e:
                    self.logger.error(f"Erreur lors du monitoring pour {search['search_url']} : {e}")
                    await asyncio.sleep(300)  # Attendre 5 minutes en cas d'erreur
            
            # Attente globale entre les cycles de recherche
            await asyncio.sleep(60)

    async def start(self):
        """Démarrer le bot Discord"""
        try:
            await self.client.login(self.discord_token)
            self.logger.info("Bot Discord connecté avec succès")
            
            # Configurer un événement de prêt
            @self.client.event
            async def on_ready():
                self.logger.info(f"Bot connecté en tant que {self.client.user}")
                # Lancer le monitoring Vinted en tâche de fond
                self.client.loop.create_task(self.monitor_vinted())
            
            # Démarrer le bot
            await self.client.start(self.discord_token)
        
        except Exception as e:
            self.logger.error(f"Erreur lors du démarrage du bot : {e}")

def main():
    """Fonction principale pour initialiser et lancer le bot"""
    # Récupérer les secrets depuis Replit
    discord_token = os.environ.get('DISCORD_TOKEN')
    channel_id = os.environ.get('CHANNEL_ID')
    
    # Vérifier la présence des tokens
    if not discord_token or not channel_id:
        print("Erreur : Token Discord ou Channel ID manquant")
        return
    
    # Configurer le logger
    logger = setup_logging()
    logger.info("Démarrage du bot Vinted")
    
    # Créer et démarrer le bot
    bot = VintedBot(discord_token, channel_id)
    
    try:
        # Utiliser asyncio pour exécuter le bot
        asyncio.run(bot.start())
    
    except KeyboardInterrupt:
        logger.info("Arrêt du bot")
    
    except Exception as e:
        logger.error(f"Erreur fatale : {e}")

# Point d'entrée du script
if __name__ == "__main__":
    main()
