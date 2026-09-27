# muz: music library maintenance tool.
# Build:  docker compose build
# Run:    docker compose run --rm muz            (dashboard)
#         docker compose run --rm muz --dupes    (any muz arguments)

FROM python:3.14-slim

# ffmpeg: --convert.  libchromaprint-tools (fpcalc): --dupes --acoustic.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libchromaprint-tools \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MUZ_LIBRARY=/music \
    # The container runs as the host user (see docker-compose.yml), which has no home here.
    HOME=/tmp \
    # 256 colours and true colour for the TUI.
    TERM=xterm-256color \
    COLORTERM=truecolor

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
# Set SPOTIFLAC=0 to build a smaller image without SpotiFLAC (--fetch then uses Deezer + LRCLIB).
ARG SPOTIFLAC=1
RUN if [ "$SPOTIFLAC" = "1" ]; then pip install ".[spotiflac]"; else pip install .; fi \
    && rm -rf /app/src /app/build

WORKDIR /music
ENTRYPOINT ["muz"]
