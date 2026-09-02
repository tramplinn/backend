#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ "$#" -ne 3 ]; then
  echo "usage: $0 IMAGE PROJECT REGISTRY" >&2
  exit 2
fi

image=$1
project=$2
registry=$3
export COMPOSE_PROJECT_NAME=$project

docker compose --env-file .env.runtime -p "$project" -f docker-compose.staging.yml config --quiet
docker pull "$image"
docker tag "$image" tramplin-api:local
docker compose --env-file .env.runtime -p "$project" -f docker-compose.staging.yml pull --quiet --ignore-buildable
docker compose --env-file .env.runtime -p "$project" -f docker-compose.staging.yml up -d --wait --wait-timeout 60 postgres redis
docker compose --env-file .env.runtime -p "$project" -f docker-compose.staging.yml run --rm --no-deps api alembic upgrade head
docker compose --env-file .env.runtime -p "$project" -f docker-compose.staging.yml up -d --no-build --remove-orphans --wait --wait-timeout 60 api algorithm-worker

docker image prune -f
docker logout "$registry"
