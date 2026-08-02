# Nexus provider policy

Supported providers:

| Provider | Router identity | Default model | Enable flag |
|---|---|---|---|
| Anthropic | `claude` | `claude-haiku-4-5-20251001` | `NEXUS_ENABLE_ANTHROPIC` |
| OpenAI | `gpt` | `gpt-4o-mini` | `NEXUS_ENABLE_OPENAI` |
| Gemini | `gemini` | `gemini-2.5-flash` | `NEXUS_ENABLE_GEMINI` |

The default order is `anthropic,openai,gemini`, with `anthropic` as the
default provider. `claude` and `gpt` are accepted aliases in configuration.

The router supports hot failover during a request: offline providers are
skipped, degraded providers are skipped when a healthy alternative exists,
and generation or output-validation failures advance to the next provider.
Health is refreshed periodically; configuration itself is read at process
startup and therefore is not hot-reloaded.

Every provider can be disabled independently. Exhausting the chain returns the
existing all-providers-failed path; it does not publish fallback text.
