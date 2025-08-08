# Import Ubuntu
FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Kolkata

# Créer le dossier de travail
RUN mkdir /app && chmod 777 /app
WORKDIR /app

# Copier les fichiers de l'application
COPY . .

# Installer les dépendances système
RUN apt update && apt install -y --no-install-recommends \
    git wget curl busybox python3 python3-pip \
    p7zip-full p7zip-rar unzip mkvtoolnix ffmpeg \
    build-essential python3-dev libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Rendre le script extract exécutable
RUN chmod +x extract

# Exposer le port
EXPOSE 8080

# Commande de démarrage
CMD ["bash", "run.sh"]