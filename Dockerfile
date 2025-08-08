# Import Ubuntu
FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Kolkata

RUN mkdir /app && chmod 777 /app
WORKDIR /app

COPY . .

RUN apt update && apt install -y --no-install-recommends \
    git wget curl busybox python3 python3-pip \
    p7zip-full p7zip-rar unzip mkvtoolnix ffmpeg \
    build-essential python3-dev libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir -r requirements.txt

RUN chmod +x extract

EXPOSE 8080

CMD ["bash", "run.sh"]