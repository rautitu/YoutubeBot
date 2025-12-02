#!/bin/bash

if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
else
    echo ".env file not found!" >&2
    exit 1
fi

# creating log directory on the host if it doesnt exist
mkdir -p "${LOG_DIR}/${CONTAINER_NAME}"

# build + recreate container (unless argument is "no-build")
if [ "$1" != "no-build" ]; then
    docker compose build > "${LOG_DIR}/${CONTAINER_NAME}/build_$(date +%Y%m%d_%H%M%S).log"
fi

docker compose down
docker compose up -d

# Optional: tail logs to a file for debugging if needed
# docker compose logs --tail=100 > "${LOG_DIR}/${CONTAINER_NAME}/startup_$(date +%Y%m%d_%H%M%S).log"

# Cleanup logs older than 60 days:
find "${LOG_DIR}/${CONTAINER_NAME}" \
    -type f -name "container_*.log" -mtime +60 -exec rm {} \;

echo "Container is running under docker compose"
echo "To view logs, run: docker compose logs -f"