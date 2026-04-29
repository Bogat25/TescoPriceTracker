# Docker Networks Setup

This stack requires two external Docker networks to be created before deployment.

## Why

The stack uses external networks to allow multiple Docker Compose stacks to communicate:
- **`public_ingress`** — shared network for services exposed to the internet (Cloudflare tunnel, reverse proxy)
- **`admin_ingress`** — shared network for admin tools (Mongo Express, Keycloak admin console)

## Automatic Setup

Run this script once on the host (Pi or dev machine):

```bash
chmod +x setup.sh
./setup.sh
```

The networks are created if they don't exist and persist across stack deployments.

## Manual Setup

Or create them manually:

```bash
docker network create public_ingress
docker network create admin_ingress
```

## Verification

List all networks:

```bash
docker network ls
```

You should see `public_ingress` and `admin_ingress` in the output.

## After Setup

Deploy the stack normally:

```bash
docker compose up -d
```

The networks don't need to be recreated after this — they persist on the host even when the stack is stopped.
