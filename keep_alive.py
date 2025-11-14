from flask import Flask

app = Flask("keep_alive")

@app.route("/")
def home():
    return "Bot Vinted actif."

def keep_alive():
    from threading import Thread
    t = Thread(target=lambda: app.run(host="0.0.0.0", port=8080))
    t.start()
