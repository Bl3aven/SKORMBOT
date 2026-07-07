FROM ghcr.io/lavalink-devs/lavalink:latest

# Install Lavalink-Spotify-Plugin
RUN apt-get update && apt-get install -y unzip && \
    curl -sL "https://github.com/retrohacker/lavalink-spotify-plugin/releases/download/5.2.1/lavalink-spotify-plugin-5.2.1.jar" -o /opt/Lavalink/plugins/lavalink-spotify-plugin.jar
