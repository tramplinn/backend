#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

: "${DOCKER_IMAGE_API:?}" "${COMPOSE_PROJECT_NAME:?}" "${CI_REGISTRY:?}"

export APP_ENV_FILE=.env.runtime

compose() {
  docker compose --env-file .env.runtime -f docker-compose.staging.yml "$@"
}

docker pull "$DOCKER_IMAGE_API"
compose config --quiet
compose up -d --wait --wait-timeout 60 postgres redis
compose run --rm --no-deps api alembic upgrade head
compose up -d --no-build --remove-orphans --wait --wait-timeout 60 api

docker image prune -f
docker logout "$CI_REGISTRY"
