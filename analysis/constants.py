# Batch sizes for micro-batch processing
PARSING_BATCH_SIZE = 10  # Files per batch (predictable, no external API)
DOC_GEN_BATCH_SIZE = 5   # Entities per batch. Staggered workers keep the
                         # whole batch well under the platform timeout.

# Maximum number of concurrent worker threads per doc-gen request. With
# 5 entities per batch and a small stagger, 5 workers gives a good
# throughput / rate-limit tradeoff.
DOC_GEN_MAX_WORKERS = 5

# How long to wait between starting each worker (seconds). Spreads the
# burst of LLM calls so a 15 req/min free-tier quota doesn't 429 the
# entire batch in lockstep.
DOC_GEN_WORKER_STAGGER_S = 0.25

# Safety limits (validated against real runs)
MAX_FILES_TO_PARSE = 100
MAX_ENTITIES_TO_DOCUMENT = 1000

# Gemini retry configuration
GEMINI_RETRY_ATTEMPTS = 4
GEMINI_RETRY_BACKOFF = [1, 2, 4, 8]  # seconds between retries
