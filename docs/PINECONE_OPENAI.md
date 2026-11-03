# OpenAI and Pinecone setup

## OpenAI
1. Create an API key at <https://platform.openai.com> (use a project key with a spending limit).
2. `OPENAI_API_KEY=…`. Defaults: `OPENAI_MODEL=gpt-4o` (reviews, structured output, temperature 0), `OPENAI_EMBEDDING_MODEL=text-embedding-3-small` (1536 dimensions).
3. Restart API **and** worker. **Settings → Integrations** shows OpenAI as *Configured*.

Cost control: reviews are bounded by `REVIEW_MAX_FILES`, `REVIEW_MAX_PATCH_BYTES`, `REVIEW_TOTAL_CHARS`, `REVIEW_MAX_BATCHES`; indexing by `INDEX_MAX_FILES` and `INDEX_MAX_FILE_BYTES`. Each review makes up to `REVIEW_MAX_BATCHES` model calls; indexing embeds every changed chunk once. Estimate with your own repositories before enabling auto-publish or indexing large monorepos.

Privacy: reviewed diffs (secrets redacted, sensitive files excluded) and indexed chunk text are sent to OpenAI — see [SECURITY.md](../SECURITY.md).

Without a key you get explicit "not configured" errors. For a local demo only, `REVIEW_USE_MOCK_LLM=true` enables a keyword matcher that is **not AI** and is labelled as such everywhere it appears.

## Pinecone
1. Create an account and an API key; set `PINECONE_API_KEY`.
2. Create a **serverless** index:
   * name = `PINECONE_INDEX_NAME` (default `synaxys-code`)
   * metric = **cosine**
   * dimension = **`EMBEDDING_DIMENSIONS`** (1536 for `text-embedding-3-small`; if you change the embedding model or its `dimensions`, create a new index and re-index)
3. Namespaces (`repo-<id>`) are created automatically on first upsert — one per repository, which is the tenant boundary.
4. On a repository's page choose **Index code**. Progress (files / chunks) is shown live; the first run indexes every eligible file, later runs only changed files (by git blob SHA). Pushes to the default branch queue incremental indexing automatically.

What is stored per chunk: vector + metadata (`repo_id`, repository name, branch, commit, path, language, line range, up to 1,500 characters of source). Not indexed: binary/generated/vendored/oversized files, `.env` and key files, and any chunk that looks like it contains a credential. Disconnecting a repository deletes its namespace.

Every indexing run first compares the index dimension with `EMBEDDING_DIMENSIONS`; a mismatch fails indexing with a clear error instead of storing wrong vectors. Per-file cleanup uses prefix listing, which is a **serverless** index feature.

`VECTOR_BACKEND=memory` (process-local store + lexical hash embeddings) exists for tests/demos only; it cannot be shared between the API and worker processes and is rejected when `APP_ENV=production`.
