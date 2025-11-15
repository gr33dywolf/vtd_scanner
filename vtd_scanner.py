import json
import time
import requests

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

    # brand_ids[]
    for bid in search.get("brand_ids", []):
        params["brand_ids[]"] = search["brand_ids"]

    r = requests.get(API_URL, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    return len(data.get("items", []))

def run_worker():
    searches = load_searches()

    # Stocke les counts initiaux
   last_counts = {}

    # Initial pass
    print("=== Initial check ===")
    for search in searches:
        name = search["name"]
        count = fetch_ads_count(search)
        last_counts[name] = count
        print(f"[{name}] {count} annonces")

    print("\n=== Start monitoring loop (5 min interval) ===\n")

    # Infinite loop for Render worker
    while True:
        time.sleep(INTERVAL)
        print("\n=== New check ===")

        for search in searches:
            name = search["name"]
            count = fetch_ads_count(search)
            diff = count - last_counts[name]

            print(f"[{name}] {count} annonces (Δ {diff})")

            last_counts[name] = count  # update

if __name__ == "__main__":
    run_worker()
