-- Add base_url column for OpenAI-compatible providers (Groq, Together,
-- DeepSeek, xAI, Mistral, Ollama, or any custom endpoint).
-- Empty string = use the provider's default URL.

ALTER TABLE agent_config ADD COLUMN IF NOT EXISTS base_url TEXT NOT NULL DEFAULT '';
