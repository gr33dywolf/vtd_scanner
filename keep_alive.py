from flask import Flask
import threading
import os

app = Flask(__name__)

@app.get("/")
def home():
    return "OK", 200


def start_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
