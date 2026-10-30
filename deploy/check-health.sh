#!/bin/sh
# Run from the deployment directory. Never start a deliberately stopped service.
set -eu
for service in app phone; do
    container_id=$(docker compose -f compose.yaml -f compose.production.yaml ps -q "$service")
    [ -n "$container_id" ] || continue
    health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container_id")
    if [ "$health" = unhealthy ]; then
        echo "$service failed consecutive local liveness checks; restarting."
        docker compose -f compose.yaml -f compose.production.yaml restart "$service"
    fi
done
