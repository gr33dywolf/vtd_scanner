# keep_alive.py
from flask import Flask
import threading
import os

app = Flask(__name__)

@app.route("/")
def home():
    return "vtd_scanner alive", 200

def run():
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)

def start():
    t = threading.Thread(target=run, daemon=True)
    t.start()

start()
