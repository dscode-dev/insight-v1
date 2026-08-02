# Nexus private-provider runtime

Nexus reads provider configuration from process environment variables. The
canonical Robozão Compose passes these values into the `nexus` container.
Provider credentials belong in the deployment secret environment, never in
source control. Copy `.env.example` only as a key-name template.

Provider adapters are registered only when their individual
`NEXUS_ENABLE_*` flag is true. Empty credentials leave an enabled adapter
offline. `NEXUS_PUBLISHER_ENABLED=false` independently prevents publication.

`OPENAI_MODEL`, `ANTHROPIC_MODEL`, and `GEMINI_MODEL` are the canonical model
variables. The older `NEXUS_OPENAI_MODEL`, `NEXUS_ANTHROPIC_MODEL`, and
`NEXUS_GEMINI_MODEL` names remain fallback aliases for compatibility.

ML-D.2 leaves all provider enable flags and the publisher disabled.
