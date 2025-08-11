FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Met à jour et installe les dépendances système nécessaires
RUN apt update && apt install -y --no-install-recommends \
    git wget curl busybox python3 python3-pip \
    p7zip-full p7zip-rar unzip mkvtoolnix ffmpeg \
    build-essential python3-dev libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# Crée le dossier de travail
RUN mkdir /app
WORKDIR /app

# Copie tous les fichiers de ton projet
COPY . .

# Installe les dépendances Python via pip
RUN pip3 install --no-cache-dir -r requirements.txt

# Expose le port 8080
EXPOSE 8080

# Démarre l’application
CMD ["python3", "-m", "isocode"]
