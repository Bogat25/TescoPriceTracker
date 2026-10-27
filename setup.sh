#!/bin/sh
# Run once on the host before deploying the stack.
# Creates the shared Docker networks if they don't already exist.
set -e

for net in public_ingress admin_ingress; do
  if docker network inspect "$net" > /dev/null 2>&1; then
    echo "  network already exists: $net"
  else
    docker network create "$net"
    echo "  created network: $net"
  fi
done

echo "Networks ready — you can now deploy the stack."
