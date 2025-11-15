import os
import json
import time
import logging
import requests
import schedule
import discord
from discord.ext import commands
from keep_alive import keep_alive

# Configuration des logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Configuration Discord
DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN')
CHANNEL_ID = int(os.environ.get('CHANNEL_ID'))

# Configuration du bot Discord
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# État des recherches précédentes
previous_results = {}

def load_search_urls():
    """Charger les URLs de recherche depuis search.json"""
    try:
        with open('search.json', 'r') as f:
            data = json.load(f)
            # Supporte les deux formats de fichier JSON
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and 'recherches' in data:
                return [item['url'] for item in data['recherches']]
            else:
                logger.error("Format de search.json non reconnu!")
                return []
    except FileNotFoundError:
        logger.error("Fichier search.json non trouvé!")
        return []
    except json.JSONDecodeError:
        logger.error("Erreur de décodage du fichier search.json")
        return []

def fetch_vinted_results(search_url):
    """
    Récupérer les résultats de Vinted 
    ATTENTION: Cette méthode est un exemple et devra être adaptée
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'fr-FR,fr;q=0.9'
        }
        response = requests.get(search_url, headers=headers)
        
        if response.status_code == 200:
            # Logique de parsing des résultats Vinted
            # À adapter selon la structure réelle de la réponse
            # Exemple simplifié - vous devrez implémenter le parsing réel
            results = [{'id': 1, 'title': 'Exemple Article'}]
            return results
        else:
            logger.warning(f"Erreur de requête: {response.status_code}")
            return []
    except Exception as e:
        logger.error(f"Erreur lors de la recherche: {e}")
        return []

async def check_new_items():
    """Vérifier les nouvelles annonces pour chaque URL"""
    search_urls = load_search_urls()
    
    for search_url in search_urls:
        try:
            current_results = fetch_vinted_results(search_url)
            
            if not current_results:
                logger.info(f"Aucun résultat pour {search_url}")
                continue
            
            # Comparer avec les résultats précédents
            new_items = [
                item for item in current_results 
                if item not in previous_results.get(search_url, [])
            ]
            
            if new_items:
                channel = bot.get_channel(CHANNEL_ID)
                if channel:
                    for item in new_items:
                        embed = discord.Embed(
                            title="Nouvelle Annonce Vinted",
                            description=item.get('title', 'Aucun titre'),
                            color=discord.Color.green()
                        )
                        # Bouton pour voir la recherche
                        view = discord.ui.View()
                        view.add_item(
                            discord.ui.Button(
                                label="Voir les annonces", 
                                style=discord.ButtonStyle.link, 
                                url=search_url
                            )
                        )
                        
                        await channel.send(embed=embed, view=view)
                        logger.info(f"Nouvelle annonce détectée pour {search_url}")
                
                # Mettre à jour les résultats précédents
                previous_results[search_url] = current_results
        
        except Exception as e:
            logger.error(f"Erreur lors du traitement de {search_url}: {e}")

@bot.event
async def on_ready():
    """Événement déclenché quand le bot est prêt"""
    logger.info(f'Bot connecté en tant que {bot.user}')
    
    # Lancement du keep_alive
    keep_alive()
    
    # Planification des vérifications périodiques
    schedule.every(360).seconds.do(lambda: bot.loop.create_task(check_new_items()))

def run_scheduler():
    """Exécution du scheduler"""
    while True:
        schedule.run_pending()
        time.sleep(1)

def main():
    """Fonction principale"""
    try:
        # Démarrer le bot Discord
        bot.loop.create_task(check_new_items())  # Première vérification immédiate
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        logger.error(f"Erreur lors du lancement du bot: {e}")

if __name__ == "__main__":
    main()
