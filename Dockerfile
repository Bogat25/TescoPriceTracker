FROM python:3.12-alpine

WORKDIR /app

RUN apk add --no-cache \
    gcc \
    musl-dev \
    libxml2-dev \
    libxslt-dev

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Allows cross-folder imports (mongo/, scraper/, config.py) regardless of working_dir
ENV PYTHONPATH=/app
