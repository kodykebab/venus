# ParaCheck CI service.
#
# The image carries a full Solidity toolchain (foundry, solc, node) because
# reviewing a real repository means building it. That also means this container
# runs untrusted code on purpose, so the build is arranged around containing it:
# an unprivileged user, a pre-populated read-only compiler cache owned by root,
# and a writable path only under /work.
#
# analyzer/sandbox.py does the per-process half (scrubbed env, rlimits); this
# does the per-container half. Neither is sufficient alone.

FROM python:3.11-slim-bookworm AS build

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

# Wheels first: this layer is the slow one (slither pulls a compiler toolchain
# for its native deps) and changes only when the pins do.
COPY analyzer/static/requirements.txt /tmp/analyzer-requirements.txt
COPY service/requirements.txt /tmp/service-requirements.txt
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir \
        -r /tmp/analyzer-requirements.txt \
        -r /tmp/service-requirements.txt

# Foundry, pinned: "latest" would make an image rebuild able to change analysis
# results without a commit explaining why.
ARG FOUNDRY_VERSION=stable
ENV FOUNDRY_DIR=/opt/foundry
RUN curl -fsSL https://foundry.paradigm.xyz | bash \
    && /opt/foundry/bin/foundryup --install ${FOUNDRY_VERSION}

# Pre-download the compilers, twice over, because the two analysis paths get
# solc from different places: solc-select for a bare .sol file, and forge's own
# svm cache for a foundry project. Without this every review pays a compiler
# download, and a blip during one surfaces as "couldn't analyze this PR".
#
# solc-select ignores SOLC_SELECT_DIR and keys off VIRTUAL_ENV, so it lands in
# /opt/venv/.solc-select and rides along with the venv copy below.
ARG SOLC_VERSIONS="0.8.24 0.8.20 0.8.19 0.8.28"
ENV VIRTUAL_ENV=/opt/venv \
    SVM_ROOT=/opt/svm \
    PATH="/opt/venv/bin:/opt/foundry/bin:$PATH"
RUN for version in ${SOLC_VERSIONS}; do solc-select install "$version"; done \
    && solc-select use 0.8.24 --always-install

# forge ignores SVM_ROOT (as of 1.8.x) and caches solc in $HOME/.svm, so the
# warm-up is pointed at a throwaway HOME and the result moved into place.
RUN mkdir -p /tmp/warm/src /tmp/warmhome \
    && printf 'contract W {}\n' > /tmp/warm/src/W.sol \
    && printf '[profile.default]\nsrc = "src"\n' > /tmp/warm/foundry.toml \
    && for version in ${SOLC_VERSIONS}; do \
         (cd /tmp/warm && HOME=/tmp/warmhome forge build --use "$version" >/dev/null) || exit 1; \
       done \
    && mv /tmp/warmhome/.svm /opt/svm \
    && rm -rf /tmp/warm /tmp/warmhome


FROM python:3.11-slim-bookworm AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:/opt/foundry/bin:$PATH" \
    VIRTUAL_ENV=/opt/venv \
    SVM_ROOT=/opt/svm \
    FOUNDRY_DISABLE_NIGHTLY_WARNING=1 \
    PARACHECK_DB=/data/paracheck.db

# git: fetching the pull request under review. nodejs/npm: hardhat and truffle
# projects. No build-essential - nothing compiles at runtime, and a compiler is
# a useful thing not to hand an attacker who lands in the container.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates nodejs npm tini \
    && rm -rf /var/lib/apt/lists/* \
    && npm cache clean --force

COPY --from=build /opt/venv /opt/venv
COPY --from=build /opt/foundry /opt/foundry
COPY --from=build /opt/svm /opt/svm

# Runs as nobody-in-particular, and owns none of its own code: an install script
# that gets execution cannot rewrite the analyzer for the next review.
# The compiler cache stays root-owned and read-only: a solc binary a reviewed
# repository could overwrite would be executed by every later review.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 paracheck \
    && mkdir -p /app /work /data \
    && chown paracheck:paracheck /work /data \
    && chmod -R a-w /opt/svm

COPY --chown=root:root analyzer /app/analyzer
COPY --chown=root:root service /app/service
COPY --chown=root:root paracheck.json /app/paracheck.json
RUN chmod -R a-w /app

WORKDIR /app
USER paracheck

# Checkouts live here, not in the image, and this is the only writable path a
# reviewed repository's build system can reach.
ENV TMPDIR=/work
VOLUME ["/data"]
EXPOSE 8000

# tini reaps whatever an install script orphans; without a real init those
# accumulate as zombies for the life of the container.
ENTRYPOINT ["/usr/bin/tini", "--"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

CMD ["python", "-m", "uvicorn", "app:app", \
     "--app-dir", "/app/service", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", \
     "--timeout-graceful-shutdown", "30"]
