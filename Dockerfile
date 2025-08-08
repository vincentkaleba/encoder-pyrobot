# Use Ubuntu 20.04 base
FROM ubuntu:20.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Kolkata \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Configure timezone and create non-root user
RUN ln -fs /usr/share/zoneinfo/$TZ /etc/localtime && \
    apt-get update && \
    apt-get install -y --no-install-recommends tzdata && \
    rm -rf /var/lib/apt/lists/* && \
    useradd -r -s /bin/bash -U appuser

# Create application directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git wget curl busybox python3 python3-pip \
    p7zip-full p7zip-rar unzip mkvtoolnix ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application files
COPY --chown=appuser:appuser . .

# Set permissions and switch user
RUN chmod +x extract && \
    chown -R appuser:appuser /app
USER appuser

# Expose application port
EXPOSE 8080

# Set entrypoint
CMD ["bash", "run.sh"]