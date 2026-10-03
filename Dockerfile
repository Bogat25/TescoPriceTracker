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

RUN addgroup -S app && adduser -S -G app app && chown -R app:app /app

# Mount point of the mongo-credential-state volume. A new named volume takes
# this directory's owner and mode, so only the app user can read it.
RUN mkdir -p /var/lib/credential-state \
    && chown app:app /var/lib/credential-state \
    && chmod 700 /var/lib/credential-state
USER app
