FROM python:3.11-slim

# Install system dependencies for PDF, EPUB, and DOCX processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libxml2-dev \
    libxslt1-dev \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory
RUN mkdir -p /data/uploads

# Expose Chainlit port
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/data

# Run Chainlit
CMD ["chainlit", "run", "moats_library/chat.py", "--host", "0.0.0.0", "--port", "8000"]
