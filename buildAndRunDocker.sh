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
docker run -d --name $CONTAINER_NAME $IMAGE_NAME

echo "Container is running!"
