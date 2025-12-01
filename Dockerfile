# Use an official Python runtime as a parent image
FROM python:3.14

# Install ffmpeg
RUN apt-get update && apt-get install -y ffmpeg

#getting this python package as well, need it for "pkill" command that was in the original solution
RUN apt-get update && apt-get install -y procps

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container
COPY . /app

# Install any necessary dependencies specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make port 8000 available to the world outside this container (if needed)
EXPOSE 8000

# Define environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Run your Python script when the container launches
CMD ["python", "youtubebot.py"]



