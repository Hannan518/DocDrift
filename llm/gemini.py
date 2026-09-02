import time
import logging
from typing import Optional

from .base import BaseLLMProvider, LLMConfigError
from .prompts import build_class_prompt, build_function_prompt, build_module_prompt

logger = logging.getLogger(__name__)

# Longest body excerpt sent to the model, keeps prompts (and costs) bounded.
MAX_PROMPT_BODY_CHARS = 6000

# Error fragments that indicate a bad/missing API key or denied access.
# These are configuration problems - retrying or switching models cannot help.
_AUTH_ERROR_FRAGMENTS = (
    'api key not valid',
    'api_key_invalid',
    'api key invalid',
    'invalid api key',
    'permission denied',
    'unauthenticated',
    'unauthorized',
)


class GeminiDocGenerator(BaseLLMProvider):
    """
    Gemini API client for docstring generation.

    Tries the current fast models in order; on 404 (model unavailable on
    the account) it falls through to the next. Handles rate limits with
    exponential backoff.
    """

    # Models tried in order. The first must work for new users on a fresh
    # API key; subsequent entries are fallbacks. Update the list when
    # Google deprecates a model - the SDK returns 404 rather than
    # redirecting to a replacement.
    MODELS = [
        'gemini-3.6-flash',
        'gemini-3.5-flash',
        'gemini-2.5-flash',
        'gemini-flash-latest',
    ]

    def __init__(self, api_key: str):
        """
        Initialize the Gemini client.

        Args:
            api_key: Google AI API key
        """
        self.api_key = api_key
        self._client = None

    @property
    def client(self):
        """Lazy-load the Gemini client."""
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def generate_docstring(
        self,
        entity_type: str,
        name: str,
        signature: str,
        body: str,
        retry_attempts: int = 3,
        retry_backoff: Optional[list] = None
    ) -> str:
        """
        Generate a docstring for a code entity.

        Args:
            entity_type: 'module', 'class', or 'function'
            name: Entity name
            signature: Full signature string
            body: Source code body
            retry_attempts: Number of retry attempts for transient errors
            retry_backoff: List of wait times between retries (seconds)

        Returns:
            Generated docstring text

        Raises:
            LLMConfigError: If the API key is missing/invalid (no retry).
            Exception: If all retry attempts fail.
        """
        if not self.api_key or self.api_key == 'your-gemini-api-key-here':
            raise LLMConfigError("Gemini API key not configured. Set GEMINI_API_KEY in .env")

        if retry_backoff is None:
            retry_backoff = [1, 2, 4]

        prompt = self._build_prompt(entity_type, name, signature, body)

        for attempt in range(retry_attempts):
            for model in self.MODELS:
                try:
                    response = self.client.models.generate_content(
                        model=model,
                        contents=prompt,
                    )
                    # Safety-blocked or empty responses expose .text as None.
                    text = (response.text or '').strip() if response is not None else ''
                    if not text:
                        raise ValueError('Empty response from model (possibly safety-blocked)')
                    return text

                except LLMConfigError:
                    raise

                except Exception as e:
                    error_str = str(e).lower()
                    error_code = getattr(e, 'code', None)

                    if any(fragment in error_str for fragment in _AUTH_ERROR_FRAGMENTS) \
                            or error_code in (401, 403):
                        raise LLMConfigError(
                            "Gemini rejected the API key. Check GEMINI_API_KEY in .env"
                        ) from e

                    # Model not available on this account - try the next model
                    if 'not found' in error_str or error_code == 404:
                        logger.debug("Model %s not available, trying next", model)
                        continue

                    # Rate limit - retry with backoff
                    if error_code == 429 or 'resource' in error_str or 'rate' in error_str:
                        if attempt < retry_attempts - 1:
                            wait_time = retry_backoff[min(attempt, len(retry_backoff) - 1)]
                            logger.warning("Rate limited, waiting %ss before retry", wait_time)
                            time.sleep(wait_time)
                            break  # Retry outer loop
                        raise Exception("Gemini rate limit exceeded after "
                                        f"{retry_attempts} attempts") from e

                    # Other error on this model - try next
                    logger.debug("Error with %s: %s", model, e)
                    continue

        raise Exception(f"All models failed after {retry_attempts} attempts")

    def _build_prompt(
        self,
        entity_type: str,
        name: str,
        signature: str,
        body: str
    ) -> str:
        """Build the appropriate prompt based on entity type."""
        body = (body or '')[:MAX_PROMPT_BODY_CHARS]

        if entity_type == 'module':
            return build_module_prompt(name, body)
        elif entity_type == 'class':
            return build_class_prompt(name, signature, body)
        else:
            return build_function_prompt(name, signature, body)
