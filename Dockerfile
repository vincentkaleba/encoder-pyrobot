# Utiliser Ubuntu 22.04 comme base
FROM ubuntu:22.04

# Configuration de l'environnement
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC
ENV PYTHONUNBUFFERED=1
ENV PYTHONFAULTHANDLER=1

# Mise à jour du système et installation des dépendances
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    build-essential \
    zlib1g-dev \
    libncurses5-dev \
    libgdbm-dev \
    libnss3-dev \
    libssl-dev \
    libreadline-dev \
    libffi-dev \
    libsqlite3-dev \
    liblzma-dev \
    wget \
    curl \
    git \
    p7zip-full \
    p7zip-rar \
    unzip \
    mkvtoolnix \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Téléchargement et installation de Python 3.12.1
RUN wget --no-check-certificate https://www.python.org/ftp/python/3.12.1/Python-3.12.1.tar.xz && \
    tar -xf Python-3.12.1.tar.xz && \
    cd Python-3.12.1 && \
    ./configure --enable-optimizations && \
    make -j $(nproc) && \
    make altinstall && \
    cd .. && \
    rm -rf Python-3.12.1 Python-3.12.1.tar.xz

# Création du dossier de travail
RUN mkdir /app && chmod 777 /app
WORKDIR /app

# Installation de pip pour Python 3.12
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12

# Copie des fichiers de l'application
COPY . .

# Installation des dépendances Python
RUN python3.12 -m pip install --no-cache-dir -r requirements.txt

# Nettoyage
RUN python3.12 -m pip cache purge

# Exposer le port
EXPOSE 8080

# Commande de démarrage
CMD ["python3.12", "-m", "isocode"]