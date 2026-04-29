FROM node:22.14-alpine3.21 AS build

WORKDIR /app

COPY package*.json ./
RUN npm install --include=dev --legacy-peer-deps --no-audit --no-fund

COPY . .

RUN npm run build

# ── Stage 2: Nginx ──────────────────────────────────────────────────────────
FROM nginx:1.27.5-alpine3.21

# The nginx docker image processes *.conf.template files in /etc/nginx/templates/
# automatically at container start using envsubst. NGINX_ENVSUBST_TEMPLATE_VARS
# (set in docker-compose.yml) restricts substitution to only the listed variables
# so that nginx's own $uri, $host, etc. are never touched.
COPY --from=build /app/dist/tesco_website/browser /usr/share/nginx/html

COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Runtime config: a tiny JS file is generated at container start from the
# template by 40-envsubst-runtime-config.sh, so the SPA can read deploy-time
# env vars (TESCO_API_BASE_URL) without being rebuilt.
COPY runtime-config.template.js /usr/share/nginx/html/runtime-config.template.js
COPY docker-entrypoint.d/40-envsubst-runtime-config.sh /docker-entrypoint.d/40-envsubst-runtime-config.sh
RUN chmod +x /docker-entrypoint.d/40-envsubst-runtime-config.sh

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
