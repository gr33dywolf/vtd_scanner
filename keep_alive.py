# keep_alive.py
from flask import Flask
import threading
import logging

app = Flask("keep_alive")

logging.getLogger("werkzeug").setLevel(logging.ERROR)

@app.route("/")
def home():
    return "vtd_scanner alive", 200

def run():
    # Run Flask in a thread so main script can continue
    app.run(host="0.0.0.0", port=8000)

def start():
    t = threading.Thread(target=run, daemon=True)
    t.start()

# Start automatically when imported
start()
