import json
import time
import requests
import threading
from keep_alive import start_server

API_URL = "https://www.vinted.fr/api/v2/catalog/items"
INTERVAL = 300  # 5 minutes


def load_searches(filename="search.json"):
    with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_ads_count(search):
    params = {
        "search_text": search["search_text"],
        "order": search.get("order", "newest_first"),
        "per_page": 100,
    }

    # Ajouter brand_ids[]
    for bid in search.get("brand_ids", []):
        params.setdefault("brand_ids[]", []).append(bid)

    r = requests.get(API_URL, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    return len(data.get("items", []))


def run_worker():
    searches = load_searches()

    # Dictionnaire pour stocker les counts initiaux
    last_counts = {}

    print("=== Initial check ===")
    for search in searches:
        name = search["name"]
        count = fetch_ads_count(search)
        last_counts[name] = count
        print(f"[{name}] {count} annonces")

    print("\n=== Start monitoring loop (5 min interval) ===\n")

    while True:
        time.sleep(INTERVAL)
        print("\n=== New check ===")

        for search in searches:
            name = search["name"]
            count = fetch_ads_count(search)
            diff = count - last_counts[name]

            print(f"[{name}] {count} annonces (Δ {diff})")

            last_counts[name] = count


if __name__ == "__main__":
    # Lance le mini serveur HTTP Render (keep alive)
    threading.Thread(target=start_server).start()

    # Lance ton scanner Vinted
    run_worker()

