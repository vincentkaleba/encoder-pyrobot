# Utiliser Ubuntu 22.04 comme base
FROM ubuntu:22.04

# Configuration de l'environnement
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Installation des dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    gnupg \
    ca-certificates \
    build-essential \
    curl \
    git \
    wget \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-dev \
    python3.12-venv \
    ffmpeg \
    mediainfo \
    mkvtoolnix \
    p7zip-full \
    p7zip-rar \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Installer pip pour Python 3.12
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12

# Création du dossier de travail
WORKDIR /app

# Création des dossiers nécessaires avec les bons droits
RUN mkdir -p /app/sessions /app/downloads /app/logs && chmod -R 777 /app

# Installation des dépendances Python
# On utilise --ignore-installed pour éviter les erreurs avec les paquets système comme blinker
COPY requirements.txt .
RUN python3.12 -m pip install --no-cache-dir --ignore-installed -r requirements.txt

# Copie du reste de l'application
COPY . .

# Exposer le port si nécessaire
EXPOSE 8080

# Commande de démarrage
CMD ["python3.12", "-m", "isocode"]