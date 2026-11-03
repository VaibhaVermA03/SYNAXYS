"""Integration status for the settings page. Booleans and NON-secret values only (never keys, secrets or tokens)."""


def integration_items(s) -> list[dict]:
    memory = s.vector_backend == "memory"
    return [
        dict(key="github_oauth", label="GitHub sign-in (OAuth)", configured=s.github_oauth_configured, env=["GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET", "GITHUB_REDIRECT_URI"],
                        detail="Lets users sign in with GitHub." if s.github_oauth_configured else "Not configured: users cannot sign in with GitHub."),
        dict(key="github_app", label="GitHub App (repository access)", configured=s.github_app_configured, env=["GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY_PATH", "GITHUB_APP_SLUG"],
                        detail="Used to read pull requests and post approved review comments." if s.github_app_configured else "Not configured: diffs cannot be fetched and reviews cannot be published."),
        dict(key="webhook", label="GitHub webhook secret", configured=bool(s.github_webhook_secret), env=["GITHUB_WEBHOOK_SECRET"],
                        detail="Webhook deliveries are verified (HMAC-SHA256)." if s.github_webhook_secret else "Not configured: the webhook endpoint rejects all deliveries."),
        dict(key="openai", label="OpenAI (reviews and embeddings)", configured=s.openai_configured, env=["OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_EMBEDDING_MODEL"],
                        detail=f"Review model: {s.openai_model}; embeddings: {s.openai_embedding_model}." if s.openai_configured
                        else ("Not configured: using the labelled mock reviewer (not AI)." if s.review_use_mock_llm else "Not configured: AI reviews cannot run.")),
        dict(key="pinecone", label="Pinecone (code search index)", configured=s.pinecone_configured or memory, env=["PINECONE_API_KEY", "PINECONE_INDEX_NAME", "EMBEDDING_DIMENSIONS"],
                        detail="Local in-memory demo store (not persistent, not for production)." if memory else
                        (f"Index: {s.pinecone_index_name}, dimension {s.embedding_dimensions}." if s.pinecone_configured else "Not configured: indexing and code search are unavailable.")),
        dict(key="encryption", label="Credential encryption key", configured=bool(s.encryption_key), env=["ENCRYPTION_KEY"],
                        detail="Stored GitHub tokens are encrypted." if s.encryption_key else "Not configured: sign-in cannot store GitHub tokens."),
    ]
