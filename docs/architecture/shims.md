# Compatibility shims for moved symbols

When a symbol moves to a lower import layer, its old import path stays as a
re-export of the same object until the retire-after point. Each row names the
old and new location as `module:symbol`, the pull request that moved it, and
the earliest point at which the old path may be removed. Every row has
import-and-call tests at both paths.

| old path | new path | PR | retire-after |
|---|---|---|---|
| `aragora.debate.cache.embeddings_lru:EmbeddingCache` | `aragora.shared.embedding_cache:EmbeddingCache` | #10301 | not before M4 seal |
| `aragora.debate.cache.embeddings_lru:EmbeddingCacheManager` | `aragora.shared.embedding_cache:EmbeddingCacheManager` | #10301 | not before M4 seal |
| `aragora.debate.cache.embeddings_lru:get_embedding_cache` | `aragora.shared.embedding_cache:get_embedding_cache` | #10301 | not before M4 seal |
| `aragora.debate.cache.embeddings_lru:get_scoped_embedding_cache` | `aragora.shared.embedding_cache:get_scoped_embedding_cache` | #10301 | not before M4 seal |
| `aragora.debate.cache.embeddings_lru:cleanup_embedding_cache` | `aragora.shared.embedding_cache:cleanup_embedding_cache` | #10301 | not before M4 seal |
| `aragora.debate.cache.embeddings_lru:reset_embedding_cache` | `aragora.shared.embedding_cache:reset_embedding_cache` | #10301 | not before M4 seal |
