# SPDX-License-Identifier: MIT
#
# Copyright (C) 2026 Guillaume Tucker

FROM python:3.13-slim-trixie
LABEL org.opencontainers.image.authors="gtucker@gtucker.io"
LABEL description="Renelick VIXI container image"

# Install system dependencies
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y --no-install-recommends --no-install-suggests \
    apt-transport-https \
    ca-certificates \
    git

# Upgrade pip
RUN python -m pip install --upgrade --root-user-action=ignore pip

# Create vixi user
RUN useradd vixi -u 1000 -d /home/vixi -s /bin/bash && \
    mkdir -p /home/vixi && \
    chown vixi: /home/vixi
USER vixi
ENV PATH=/home/vixi/.local/bin:$PATH

# Install VIXI with dependencies
RUN mkdir /home/vixi/build
WORKDIR /home/vixi/build
COPY --chown=vixi vixi vixi
COPY --chown=vixi pyproject.toml .
RUN pip install .
WORKDIR /home/vixi
RUN rm -rf build

ENTRYPOINT ["/home/vixi/.local/bin/renelick"]
