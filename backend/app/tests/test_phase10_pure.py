from types import SimpleNamespace as NS
from app.services.integration_status import integration_items

SECRETS = {"github_client_secret": "gcs-SECRET-1", "github_webhook_secret": "whsec-SECRET-2", "openai_api_key": "sk-SECRET-3", "pinecone_api_key": "pcsk-SECRET-4",
           "encryption_key": "ENC-SECRET-5", "github_app_private_key": "PEM-SECRET-6"}


def S(**kw):
    base = {**SECRETS, "github_oauth_configured": True, "github_app_configured": True, "openai_configured": True, "openai_model": "gpt-4o", "openai_embedding_model": "te3",
            "pinecone_configured": True, "pinecone_index_name": "idx", "embedding_dimensions": 1536, "vector_backend": "pinecone", "review_use_mock_llm": False}
    return NS(**{**base, **kw})


def test_status_never_contains_secret_values():
    text = str(integration_items(S()))
    assert not any(v in text for v in SECRETS.values())
    assert "idx" in text and "gpt-4o" in text                                    # non-secret config is shown


def test_unconfigured_state_is_explicit_with_the_env_vars_to_set():
    items = {i["key"]: i for i in integration_items(S(github_oauth_configured=False, github_app_configured=False, github_webhook_secret="", openai_configured=False, pinecone_configured=False, encryption_key=""))}
    assert all(not i["configured"] for i in items.values())
    assert "GITHUB_CLIENT_ID" in items["github_oauth"]["env"] and "GITHUB_WEBHOOK_SECRET" in items["webhook"]["env"] and "rejects all deliveries" in items["webhook"]["detail"]
    assert "AI reviews cannot run" in items["openai"]["detail"] and "unavailable" in items["pinecone"]["detail"]


def test_mock_and_memory_modes_are_labelled_not_presented_as_real():
    items = {i["key"]: i for i in integration_items(S(openai_configured=False, review_use_mock_llm=True, pinecone_configured=False, vector_backend="memory"))}
    assert not items["openai"]["configured"] and "mock reviewer (not AI)" in items["openai"]["detail"]
    assert items["pinecone"]["configured"] and "not persistent" in items["pinecone"]["detail"]


def test_database_url_normalisation():
    from app.core.db_url import normalize_database_url as n
    assert n("postgres://u:p@h:5432/d") == "postgresql+psycopg://u:p@h:5432/d" and n("postgresql://u@h/d") == "postgresql+psycopg://u@h/d"
    assert n("postgresql+psycopg://u@h/d") == "postgresql+psycopg://u@h/d" and n("sqlite:///./x.db") == "sqlite:///./x.db" and n("  postgres://u@h/d \n") == "postgresql+psycopg://u@h/d" and n("") == ""
