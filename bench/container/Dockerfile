FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

ARG T3_VERSION=0.0.46-nightly.20261007.2787
ARG CLAUDE_VERSION=2.1.296
ARG CODEX_VERSION=0.162.1

COPY node /usr/local/bin/node

ENV DEBIAN_FRONTEND=noninteractive \
    HOME=/opt/bench-home \
    CODEX_HOME=/opt/bench-home/.codex \
    T3CODE_HOME=/bench/t3 \
    XDG_CONFIG_HOME=/opt/bench-home/.config \
    XDG_DATA_HOME=/opt/bench-home/.local/share \
    XDG_STATE_HOME=/opt/bench-home/.local/state \
    NPM_CONFIG_CACHE=/tmp/bench-npm-cache \
    npm_config_cache=/tmp/bench-npm-cache \
    T3CODE_TELEMETRY_ENABLED=0 \
    T3CODE_OTEL_SDK_DISABLED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl git libatomic1 nodejs npm python3 tini openssl util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && chmod 0555 /usr/local/bin/node \
    && npm install --global "@anthropic-ai/claude-code@${CLAUDE_VERSION}" "@openai/codex@${CODEX_VERSION}" \
    && useradd --home-dir /opt/bench-home --no-create-home --uid 1000 --shell /bin/bash bench \
    && useradd --home-dir /opt/bench-home --no-create-home --uid 1001 --shell /bin/bash bench-worker \
    && install -d -o bench -g bench /opt/bench-home /bench/t3 /bench/ws /bench/pkg /bench/results \
      /opt/bench-home/.claude /opt/bench-home/.codex /opt/bench-home/.agents \
      /opt/bench-home/.config /opt/bench-home/.local/share /opt/bench-home/.local/state \
      /opt/bench /run/secrets

COPY t3-runtime/ /opt/t3-runtime/
RUN ln -s /opt/t3-runtime/t3 /usr/local/bin/t3 \
    && claude --version | grep -F "${CLAUDE_VERSION}" \
    && codex --version | grep -F "${CODEX_VERSION}" \
    && t3 --version | grep -F "${T3_VERSION}"

COPY audit_models.py driver.py gateway.py github_sidecar.py host_observations.py identity_metadata.py model_policy.py smoke.py smoke_helper.py start-container.sh /opt/bench/
COPY native_exec.py /opt/bench/native_exec.py
RUN mv /usr/local/bin/claude /usr/local/bin/claude-native \
    && mv /usr/local/bin/codex /usr/local/bin/codex-native \
    && chmod 0555 /opt/bench/native_exec.py \
    && ln -s /opt/bench/native_exec.py /usr/local/bin/claude \
    && ln -s /opt/bench/native_exec.py /usr/local/bin/codex
RUN chmod 0555 /opt/bench/start-container.sh /opt/bench/driver.py \
      /opt/bench/gateway.py /opt/bench/github_sidecar.py /opt/bench/model_policy.py \
      /opt/bench/audit_models.py /opt/bench/smoke.py /opt/bench/smoke_helper.py

EXPOSE 3773
USER root
ENTRYPOINT ["/usr/bin/tini", "--", "/opt/bench/start-container.sh"]
