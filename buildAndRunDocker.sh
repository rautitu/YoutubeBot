#!/bin/bash

# Define variables
IMAGE_NAME="youtubebot"
CONTAINER_NAME="youtubebot-container"

# Step 1: Build the Docker image
echo "Building Docker image..."
docker build -t $IMAGE_NAME .

# Step 2: Stop and remove existing container (if any)
if [ $(docker ps -a -q -f name=$CONTAINER_NAME) ]; then
    echo "Stopping and removing existing container..."
    docker stop $CONTAINER_NAME
    docker rm $CONTAINER_NAME
fi

# Step 3: Run the new container
echo "Running the new container..."
docker run -d --name $CONTAINER_NAME $IMAGE_NAME

echo "Container is running!"
