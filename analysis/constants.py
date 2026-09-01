# Batch sizes for micro-batch processing
PARSING_BATCH_SIZE = 10  # Files per batch (predictable, no external API)
DOC_GEN_BATCH_SIZE = 5   # Entities per batch (accounts for Gemini retry variance)

# Safety limits (will be tuned after benchmarking httpx)
MAX_FILES_TO_PARSE = 100
MAX_ENTITIES_TO_DOCUMENT = 300

# Gemini retry configuration
GEMINI_RETRY_ATTEMPTS = 4
GEMINI_RETRY_BACKOFF = [1, 2, 4, 8]  # seconds between retries
