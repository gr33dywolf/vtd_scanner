# Dockerfile - Python 3.11 + Playwright Chromium
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ca-certificates curl libnss3 libatk-bridge2.0-0 libgtk-3-0 libx11-xcb1 \
    libxcomposite1 libxdamage1 libxrandr2 libgbm1 libasound2 fonts-liberation wget \
    build-essential --no-install-recommends && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN python -m playwright install --with-deps chromium

COPY . /app
ENV PORT=8080
EXPOSE 8080

CMD ["python", "vtd_scanner.py"]
