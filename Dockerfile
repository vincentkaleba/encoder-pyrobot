# Utiliser une image Python officielle 3.12 (plus stable et rapide que le build manuel)
FROM python:3.12-slim-bookworm

# Configuration de l'environnement
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Installation des dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    mediainfo \
    mkvtoolnix \
    p7zip-full \
    p7zip-rar \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Création du dossier de travail
WORKDIR /app

# Création des dossiers nécessaires avec les bons droits
RUN mkdir -p /app/sessions /app/downloads /app/logs && chmod -R 777 /app

# Installation de pip et des dépendances
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copie du reste de l'application
COPY . .

# Exposer le port si nécessaire
EXPOSE 8080

# Commande de démarrage
CMD ["python", "-m", "isocode"]