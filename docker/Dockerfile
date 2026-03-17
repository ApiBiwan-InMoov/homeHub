FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libasound2-dev \
    libpulse0 \
    libportaudio2 \
    portaudio19-dev \
    alsa-utils \
    avahi-daemon \
    libavahi-client3 \
    fonts-noto-color-emoji \
    curl \
    ca-certificates \
    && update-ca-certificates \
    # Install librespot from raspotify (best way to get a pre-built binary for debian) \
    && curl -fsSL -o raspotify.deb https://github.com/dtcooper/raspotify/releases/download/0.48.1/raspotify_0.48.1.librespot.v0.8.0-ea81314_amd64.deb \
    && dpkg-deb -x raspotify.deb /tmp/raspotify \
    && cp /tmp/raspotify/usr/bin/librespot /usr/local/bin/ \
    && rm -rf raspotify.deb /tmp/raspotify \
    # Fetch latest cloudflared deb instead of a hard-coded version \
    && curl -fsSL -o cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb \
    && dpkg -i cloudflared.deb || apt-get -y -f install \
    && rm -f cloudflared.deb \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080
COPY docker/start.sh /app/docker/start.sh
RUN chmod +x /app/docker/start.sh
CMD ["/app/docker/start.sh"]
