# Use a Python base image
FROM python:3.12-slim

# Install system dependencies required for building packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    make \
    gcc \
    g++ \
    cmake \
    libtesseract-dev \
    libleptonica-dev \
    tesseract-ocr \
    libjpeg-dev \
    zlib1g-dev \
    libopenjp2-7-dev \
    libpng-dev \
    libtiff-dev \
    libglib2.0-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy your entire project into the container
COPY . /app

# Install dependencies from both requirement files
RUN pip install --no-cache-dir -r requirements.txt

# By default, just set up a command. We'll override it in docker-compose
CMD ["python", "client.py"]