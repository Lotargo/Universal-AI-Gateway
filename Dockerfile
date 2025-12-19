# Use official Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
# curl: for installing poetry (if not using pip) and healthchecks
# build-essential: for compiling some python extensions if needed
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
# We install via pip to ensure it's available in the system python environment
RUN pip install poetry

# Configure Poetry
# We do not create a virtualenv because we are in a container (isolation is already provided)
# This also prevents conflicts if a local 'env/' folder is mounted into the container
RUN poetry config virtualenvs.create false

# Copy dependency files first to cache this layer
COPY pyproject.toml poetry.lock ./

# Install dependencies
# --no-interaction: do not ask any interactive questions
# --no-ansi: disable ANSI output
RUN poetry install --no-interaction --no-ansi --no-root

# Copy the rest of the application code
COPY . .

# Expose the application port
EXPOSE 8001

# Run the application
# --reload: allows for hot-reloading when code changes (requires volume mount)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]
