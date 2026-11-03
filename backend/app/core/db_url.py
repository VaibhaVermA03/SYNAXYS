"""DATABASE_URL normalisation (stdlib only): hosts such as Render hand out postgres:// or postgresql://,
but SQLAlchemy must be told to use the psycopg (v3) driver this project ships."""


def normalize_database_url(url: str) -> str:
    url = (url or "").strip()
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url
