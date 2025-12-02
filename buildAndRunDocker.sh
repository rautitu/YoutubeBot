#!/bin/bash

# Load .env file
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
else
    echo ".env file not found!"
    exit 1
fi

# Create the log directory on the host (silently)
mkdir -p "${LOG_DIR}/${CONTAINER_NAME}"

# 1. BUILD
if [ "$1" != "no-build" ]; then
    echo "Building docker image..."
    docker compose build 
fi

# 2. STOP OLD CONTAINER 
docker compose down

# 3. START SILENTLY
# -d is detached
# --quiet (or -q) hides the "Container Started" progress bars
# --remove-orphans cleans up old containers not in the compose file
docker compose up -d --quiet --remove-orphans

# Cleanup logs older than 60 days:
find "${LOG_DIR}/${CONTAINER_NAME}" \
    -type f -name "container_*.log" -mtime +60 -exec rm {} \;

echo "Success! ${CONTAINER_NAME} is running in the background."