# Search and retrieval

`POST /api/v1/search` accepts `mode: "semantic"`, `"keyword"`, or `"hybrid"`. The default is hybrid; `use_hybrid_search: false` selects semantic-only search for compatibility with the API specification. Keyword-only search works without Gemini or Pinecone credentials. Hybrid results use Reciprocal Rank Fusion with a constant of 60. Gemini is the exclusive embedding provider.

Semantic search embeds the query and asks Pinecone for candidate vector IDs. Keyword search uses PostgreSQL `websearch_to_tsquery` and `ts_rank_cd`; SQLite has a simple text-match path for local tests. In both modes the API fetches canonical chunk text and source metadata from NeonDB, then returns only chunks whose documents are complete. Pinecone filter metadata is used for service, environment, and source type. Date filters are applied in NeonDB so older vectors without indexed timestamp metadata remain searchable.

Scores are ranking signals, not probabilities, and scores from semantic, keyword, and hybrid modes are not comparable. Cross-encoder reranking is not configured; requesting it returns `503`.
