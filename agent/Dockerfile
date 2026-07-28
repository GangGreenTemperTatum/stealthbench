FROM python:3.14-slim

# System tools for offensive security testing
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    netcat-openbsd \
    jq \
    dnsutils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Keep the container alive — harness exec's commands into it
CMD ["sleep", "infinity"]
