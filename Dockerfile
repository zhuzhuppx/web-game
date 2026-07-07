FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY chess/server.py ./
ENV PYTHONUNBUFFERED=1
EXPOSE 8656
CMD ["python3", "server.py"]
