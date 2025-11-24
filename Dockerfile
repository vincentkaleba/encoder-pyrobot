# Import Ubuntu
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Préparer le répertoire de l'application
RUN mkdir /app && chown 1000:1000 /app
WORKDIR /app

# Copier les sources en deux étapes pour profiter du cache Docker
COPY requirements.txt /app/requirements.txt
COPY . /app

# Installer dépendances système et utilitaires (FFmpeg inclus)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
        wget \
        curl \
        python3 \
        python3-pip \
        python3-venv \
        p7zip-full \
        unzip \
        mkvtoolnix \
        ffmpeg \
        build-essential \
        libxml2-dev \
        libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# Mettre à jour pip et installer les dépendances Python (no-cache)
RUN python3 -m pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r /app/requirements.txt

# Créer un utilisateur non-root pour exécuter l'application
RUN useradd -m -u 1000 -s /bin/bash isocode \
    && chown -R isocode:isocode /app

USER isocode

# Exposer (optionnel) - le bot n'ouvre pas de port HTTP par défaut
EXPOSE 8080

# Lancer le bot via run.sh (doit être exécutable)
CMD ["bash", "run.sh"]