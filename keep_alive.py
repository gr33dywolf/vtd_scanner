from flask import Flask

app = Flask('keep_alive')

@app.route('/')
def home():
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
