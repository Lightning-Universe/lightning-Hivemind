FROM debian:bookworm

ENV DEBIAN_FRONTEND="noninteractive"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    python3-full \
    python3-pip \
    python3-packaging \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --break-system-packages -r requirements.txt

COPY tests/requirements.txt tests/requirements.txt
RUN python3 -m pip install --break-system-packages -r tests/requirements.txt

COPY . ./

RUN python3 -m pip install --break-system-packages .
