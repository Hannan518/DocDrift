import time
import logging
from typing import Optional

from .base import BaseLLMProvider
from .prompts import build_docstring_prompt, build_class_prompt, build_function_prompt, build_module_prompt

logger = logging.getLogger(__name__)


class GeminiDocGenerator(BaseLLMProvider):
    """
    Gemini API client for docstring generation.
    
    Supports gemini-2.0-flash with automatic fallback to gemini-1.5-flash.
    Handles rate limits with exponential backoff.
    """
    
    MODELS = ['gemini-2.0-flash', 'gemini-1.5-flash']
    
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
        retry_attempts: int = 4,
        retry_backoff: list = None
    ) -> str:
        """
        Generate a docstring for a code entity.
        
        Args:
            entity_type: 'module', 'class', or 'function'
            name: Entity name
            signature: Full signature string
            body: Source code body
            retry_attempts: Number of retry attempts
            retry_backoff: List of wait times between retries (seconds)
        
        Returns:
            Generated docstring text
        
        Raises:
            Exception: If all retry attempts fail
        """
        if retry_backoff is None:
            retry_backoff = [1, 2, 4, 8]
        
        prompt = self._build_prompt(entity_type, name, signature, body)
        
        for attempt in range(retry_attempts):
            for model in self.MODELS:
                try:
                    response = self.client.models.generate_content(
                        model=model,
                        contents=prompt,
                    )
                    return response.text.strip()
                
                except Exception as e:
                    error_str = str(e).lower()
                    error_code = getattr(e, 'code', None)
                    
                    # If model not found, try next model
                    if 'not found' in error_str or 'invalid' in error_str or error_code == 404:
                        logger.debug(f"Model {model} not available, trying next")
                        continue
                    
                    # Rate limit - retry with backoff
                    if error_code == 429 or 'resource' in error_str or 'rate' in error_str:
                        if attempt < retry_attempts - 1:
                            wait_time = retry_backoff[min(attempt, len(retry_backoff) - 1)]
                            logger.warning(f"Rate limited, waiting {wait_time}s before retry")
                            time.sleep(wait_time)
                            break  # Retry outer loop
                        else:
                            raise Exception(f"Rate limit exceeded after {retry_attempts} attempts")
                    
                    # Other error on this model - try next
                    logger.debug(f"Error with {model}: {e}")
                    continue
            
            # If we exhausted all models on this attempt, continue to next attempt
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
        if entity_type == 'module':
            return build_module_prompt(name, body)
        elif entity_type == 'class':
            return build_class_prompt(name, signature, body)
        else:
            return build_function_prompt(name, signature, body)
