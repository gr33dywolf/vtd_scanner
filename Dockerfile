# Dockerfile - image Python + Playwright (Chromium)
FROM python:3.11-slim

# Install dependencies for Playwright/Chromium
RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
    libnss3 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    fonts-liberation \
    wget \
    --no-install-recommends && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN python -m playwright install --with-deps chromium

# Copy app
COPY . /app

# Expose port for keep_alive
ENV PORT=8080
EXPOSE 8080

# Use a non-root user (optional)
# RUN useradd -m appuser && chown -R appuser /app
# USER appuser

CMD ["python", "vtd_scanner.py"]
