FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends openjdk-17-jdk-headless libatomic1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY ChessProxy.java /app/
RUN javac -encoding UTF-8 ChessProxy.java
COPY pikafish /app/pikafish_data/pikafish
COPY pikafish.nnue /app/pikafish_data/pikafish.nnue
RUN chmod +x /app/pikafish_data/pikafish
EXPOSE 8656
CMD ["java", "ChessProxy"]
