# Local LLM serving: endpoints and clients


| Server | OpenAI `base_url` | Anthropic base URL | Auth |
|---|---|---|---|
| mlx_lm.server | `http://127.0.0.1:8080/v1` | — | none |
| oMLX | `http://127.0.0.1:8000/v1` | `http://127.0.0.1:8000` | `--api-key` |
| LM Studio | `http://127.0.0.1:1234/v1` | `http://127.0.0.1:1234` | optional |
| llama-server | `http://127.0.0.1:8080/v1` | `http://127.0.0.1:8080` | `--api-key` |
| vLLM | `http://127.0.0.1:8000/v1` | `http://127.0.0.1:8000` | `--api-key` |

- OpenAI SDKs take the `/v1` base; Anthropic SDKs and Claude Code take the server root (they append `/v1/messages`). The model name must be an id from `GET /v1/models` (set it with `-a`, `--served-model-name`, `--identifier` or an oMLX alias). Keyless servers still need a non-empty dummy key in most clients.
```python
from openai import OpenAI
c = OpenAI(base_url="http://127.0.0.1:8080/v1", api_key="local")
r = c.chat.completions.create(model="<id>", messages=[{"role": "user", "content": "ping"}], temperature=0, max_tokens=64)
```

**Claude Code against a local Anthropic-compatible server** (from the Claude Code gateway docs; Anthropic does not support routing Claude Code to non-Claude models, so treat it as an experiment and prefer per-shell exports over global settings):
```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8080 ANTHROPIC_AUTH_TOKEN="$LLAMA_API_KEY" ANTHROPIC_MODEL=<id>
export ANTHROPIC_DEFAULT_OPUS_MODEL=<id> ANTHROPIC_DEFAULT_SONNET_MODEL=<id> ANTHROPIC_DEFAULT_HAIKU_MODEL=<id> CLAUDE_CODE_SUBAGENT_MODEL=<id>
export CLAUDE_CODE_MAX_CONTEXT_TOKENS=<server context> CLAUDE_CODE_ATTRIBUTION_HEADER=0
```
- MCP tool search is off for non-first-party base URLs: every MCP tool definition loads up front and eats context. Setting `ENABLE_TOOL_SEARCH=true` makes requests fail unless the server handles `tool_reference` blocks.
- Claude Code sends Claude-API fields and beta headers (adaptive thinking, effort, context management); on rejections it retries without some of them; `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1` strips beta headers and fields.
- A stream silent for 5 minutes is aborted: the server must stream pings during long prefill (llama-server does every 30 s); `API_TIMEOUT_MS` (default 600000) bounds the whole request.
- `CLAUDE_CODE_MAX_CONTEXT_TOKENS` applies to model ids not starting with `claude-`; without `/v1/messages/count_tokens`, `/context` shows estimates. The attribution-header setting keeps the system-prompt prefix identical so the local prefix cache can hit. Remote Control is unavailable with a non-Anthropic base URL. Run `/status` to confirm the base URL and credential in use.

**LibreChat** (`librechat.yaml` next to `.env`; with Docker, bind-mount it via `docker-compose.override.yml` and restart):
```yaml
version: 1.3.5            # the config version your LibreChat release documents
endpoints:
  custom:
    - name: "Local"
      apiKey: "${LOCAL_LLM_KEY}"
      baseURL: "http://host.docker.internal:8080/v1"   # localhost when LibreChat is not in Docker
      models: { default: ["<id>"], fetch: true }
      titleConvo: true
      titleModel: "current_model"
      modelDisplayLabel: "Local"
```
From a container the server must listen beyond loopback — then require a key. `dropParams: [...]` removes request fields a server rejects.
