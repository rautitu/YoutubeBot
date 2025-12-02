#!/bin/bash

# Load .env file
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
else
    echo ".env file not found!"
    exit 1
fi

# Create the log directory on the host
mkdir -p "${LOG_DIR}/${CONTAINER_NAME}"

# Build + recreate container (unless argument is "no-build")
if [ "$1" != "no-build" ]; then
    docker compose build
fi

docker compose down          # Stop & remove container cleanly
docker compose up -d         # Start detached

# Optional: show logs live (but compose already timestamps them)
#docker compose logs -f youtubebot &

## Cleanup logs older than 60 days:
#find "${LOG_DIR}/${CONTAINER_NAME}" \
#    -type f -name "container_*.log" -mtime +60 -exec rm {} \;

echo "Container is running under Docker Compose!"
