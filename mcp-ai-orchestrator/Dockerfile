# Use an official Python runtime based on Debian 12 (Bookworm) for stability
FROM python:3.11-slim-bookworm

# Set the working directory in the container
WORKDIR /workspace

# --- Install Docker CLI ---
# We need this so the docker_server.py can send commands to the host's Docker socket
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    docker.io \
    git \
    && rm -rf /var/lib/apt/lists/*
# --- End of Docker CLI install ---

# Copy the requirements file
COPY ./requirements.txt /workspace/requirements.txt

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r /workspace/requirements.txt

# Copy the entire app and config directory into the container
COPY ./app /workspace/app
COPY ./config /workspace/config

# The CMD will be provided by docker-compose.yml