#!/bin/sh
set -eu

if [ -z "${ANTHROPIC_API_KEY:-}" ] || [ -z "${OPENAI_API_KEY:-}" ]; then
    echo 'bench runtime credentials are unavailable' >&2
    exit 2
fi

mkdir -p "$CODEX_HOME" "$HOME/.claude" "$HOME/.agents" /bench/t3 /bench/ws
chmod 0700 /bench/t3
chown -R 1001:1001 "$HOME" /bench/ws /bench/results
if [ ! -d /bench/ws/.git ]; then
    git -C /bench/ws init --quiet
    chown -R 1001:1001 /bench/ws/.git
fi
# Codex 0.162.1 ignores OPENAI_BASE_URL for model traffic; route its built-in
# OpenAI provider to the gateway with the supported openai_base_url setting.
# Turn off the paid features that `codex features list` reports as default-on
# in 0.162.1, and live web search, so a normal turn sends no server-side tool
# that the gateway would reject.
cat >"$CODEX_HOME/config.toml" <<'TOML'
openai_base_url = "https://gateway.bench.test:8443/v1"
web_search = "disabled"

[features]
image_generation = false
computer_use = false
fast_mode = false
ultrafast_mode = false
browser_use = false

[model_providers.bench-gateway]
name = "Bench model gateway"
base_url = "https://gateway.bench.test:8443/v1"
wire_api = "responses"
requires_openai_auth = true
supports_websockets = false
TOML
chmod 0600 "$CODEX_HOME/config.toml"
chown 1001:1001 "$CODEX_HOME/config.toml"

# Feed the API key through stdin. Neither command writes it to stdout or an image layer.
if ! printf '%s' "$OPENAI_API_KEY" | codex login --with-api-key >/dev/null 2>&1; then
    echo 'Codex API-key initialization failed' >&2
    exit 2
fi

export ANTHROPIC_BASE_URL='https://gateway.bench.test:8443'
# The pinned isolated catalog exposes Haiku thinking=false. These native
# Claude controls keep startup and native children at that cost setting;
# the gateway independently rejects any request that tries to enable it.
export MAX_THINKING_TOKENS=0
export CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING=1
export OPENAI_BASE_URL='https://gateway.bench.test:8443/v1'
export NPM_CONFIG_CACHE=/tmp/bench-npm-cache
export npm_config_cache=/tmp/bench-npm-cache
export ANTHROPIC_API_KEY OPENAI_API_KEY
# Babysitter starts pass GH_HOST=github.com, which the agent alone resolves to the
# synthetic sidecar; benchctl admits only synthetic values. Other runs keep the bench host.
export GH_HOST="${GH_HOST:-github.bench.test}"
export GH_TOKEN='bench-synthetic-token'
export GITHUB_TOKEN='bench-synthetic-token'

cd /bench/ws
exec t3 serve --base-dir /bench/t3 --host 0.0.0.0 --port 3773 --no-browser \
    --auto-bootstrap-project-from-cwd \
    > /bench/t3/serve.log 2>&1
