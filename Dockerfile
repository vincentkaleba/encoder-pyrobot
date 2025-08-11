FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Installer les prérequis pour ajouter le repo et installer python 3.10
RUN apt update && apt install -y --no-install-recommends \
    software-properties-common wget curl git busybox \
    p7zip-full p7zip-rar unzip mkvtoolnix ffmpeg \
    build-essential python3.10 python3.10-dev python3.10-distutils \
    libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# Installer pip pour python3.10
RUN wget https://bootstrap.pypa.io/get-pip.py && python3.10 get-pip.py && rm get-pip.py

# Créer le dossier de travail
RUN mkdir /app && chmod 777 /app
WORKDIR /app

# Copier les fichiers de l'application
COPY . .

# Installer les dépendances Python avec python3.10
RUN python3.10 -m pip install --no-cache-dir -r requirements.txt

# Exposer le port
EXPOSE 8080

# Lancer le bot avec python3.10
CMD ["python3.10", "-m", "isocode"]
