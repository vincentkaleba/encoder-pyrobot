# Utiliser Ubuntu 20.04 comme base
FROM ubuntu:20.04

# Configuration de l'environnement
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC
ENV PYTHONUNBUFFERED=1

# Créer le dossier de travail
RUN mkdir /app && chmod 777 /app
WORKDIR /app

# Installer les dépendances système et Python 3.10
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa -y && \
    apt-get update && apt-get install -y --no-install-recommends \
    git wget curl busybox python3.10 python3.10-dev python3.10-distutils \
    p7zip-full p7zip-rar unzip mkvtoolnix ffmpeg \
    build-essential libxml2-dev libxslt1-dev && \
    rm -rf /var/lib/apt/lists/*

# Installer pip pour Python 3.10
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.10

# Copier les fichiers de l'application (fait après l'installation des dépendances pour mieux utiliser le cache Docker)
COPY . .

# Installer les dépendances Python
RUN python3.10 -m pip install --no-cache-dir -r requirements.txt

# Rendre le script extract exécutable
# RUN chmod +x extract

# Exposer le port
EXPOSE 8080

# Commande de démarrage
CMD ["python3.10", "-m", "isocode"]