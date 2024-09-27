#!/bin/bash

# Define variables
#IMAGE_NAME="youtubebot"
#CONTAINER_NAME="youtubebot-container"
# Load variables from .env file
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
else
    echo ".env file not found!"
    exit 1
fi

#creating a folder for logs (if it doesnt exists)
mkdir -p "${LOG_DIR}/${CONTAINER_NAME}"

#creating a timestamp for the log file name
LOG_TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

# Step 1: Build the Docker image
# if argument one is "no-build" then skip this
if [ "$1" != "no-build" ]; then
    echo "Building Docker image..."
    docker build -t $IMAGE_NAME .
else
    echo "Skipping image build..."
fi

# Step 2: Stop and remove existing container (if any)
# Check if the container is running
if [ -n "$(docker ps -q -f name=$CONTAINER_NAME)" ]; then
    echo "Stopping running container..."
    docker stop $CONTAINER_NAME
fi

# Remove the container (whether stopped or exited)
if [ -n "$(docker ps -a -q -f name=$CONTAINER_NAME)" ]; then
    echo "Removing existing container(s)..."
    docker rm $CONTAINER_NAME
fi

# Step 3: Run the new container
echo "Running the new container..."
docker run \
    --restart=on-failure \
    -d \
    --name "$CONTAINER_NAME" \
    $IMAGE_NAME

# Step 4: Attaching a logging mechanism and a cleanup mechanism for old logs
docker logs -f "$CONTAINER_NAME" >> "${LOG_DIR}/${CONTAINER_NAME}/container_${LOG_TIMESTAMP}.log" 2>&1 &


# Function to cleanup log files that are older than 60 days
cleanup_logs() {
    find "${LOG_DIR}/${CONTAINER_NAME}" -type f -name "container_*.log" -mtime +60 -exec rm {} \;
}

# Call the cleanup function after starting logging
cleanup_logs

echo "Container is running!"
