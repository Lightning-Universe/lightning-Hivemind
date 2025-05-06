FROM ubuntu:22.04

ENV DEBIAN_FRONTEND="noninteractive"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    python3-full \
    python3-pip \
    python3-packaging \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . ./
RUN python3 -m pip install . -r tests/requirements.txt
