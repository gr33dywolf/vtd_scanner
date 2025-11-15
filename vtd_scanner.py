import json
import time
import threading
from keep_alive import start_server
from playwright.sync_api import sync_playwright

INTERVAL = 300  # Intervalle entre chaque check (en secondes)


def load_searches(filename="search.json"):
    """
    Charge les recherches depuis un fichier JSON.
    Chaque recherche doit avoir un nom et une URL complète.
    """
    with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_ads_count(search, page):
    """
    Utilise Playwright pour récupérer le nombre total d'annonces sur Vinted pour une recherche donnée.
    Supporte l'URL complète fournie dans search['url'].
    """
    url = search.get("url")
    if not url:
        raise ValueError(f"Pas d'URL définie pour la recherche '{search.get('name')}'")

    page.goto(url)
    time.sleep(2)  # Temps initial pour charger la page

    # Scroll infini pour charger toutes les annonces
    last_height = 0
    while True:
        page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
        time.sleep(2)
        new_height = page.evaluate("document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

    # Compter toutes les annonces visibles
    items = page.query_selector_all("div.catalog-item")
    return len(items)


def run_worker():
    searches = load_searches()
    last_counts = {}

    print("=== Initial check ===")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Premier check
        for search in searches:
            name = search["name"]
            count = fetch_ads_count(search, page)
            last_counts[name] = count
            print(f"[{name}] {count} annonces")

        print("\n=== Start monitoring loop (interval {INTERVAL}s) ===\n")

        while True:
            time.sleep(INTERVAL)
            print("\n=== New check ===")

            for search in searches:
                name = search["name"]
                count = fetch_ads_count(search, page)
                diff = count - last_counts[name]
                print(f"[{name}] {count} annonces (Δ {diff})")
                last_counts[name] = count


if __name__ == "__main__":
    # Lance le mini serveur HTTP Render (keep alive)
    threading.Thread(target=start_server).start()

    # Lance le scanner Vinted avec Playwright
    run_worker()
