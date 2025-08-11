# Image officielle Python 3.11 légère (slim)
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Créer le dossier de travail
RUN mkdir /app
WORKDIR /app

# Copier les fichiers de l'application
COPY . .

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Exposer le port
EXPOSE 8080

# Lancer le bot
CMD ["python", "-m", "isocode"]
