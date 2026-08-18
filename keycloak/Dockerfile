FROM quay.io/keycloak/keycloak:26.0.5

# Portainer Git deployments do not reliably materialize repository-relative
# bind-mounted files. Bake both startup inputs into the immutable image so a
# missing checkout file cannot turn into a directory at container creation.
COPY --chmod=0755 keycloak/docker-entrypoint.sh /opt/keycloak/bin/tesco-entrypoint.sh
COPY --chmod=0644 keycloak/realm-template.json /opt/keycloak/realm-template.json
