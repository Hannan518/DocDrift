"""LLM Integration Module

This module provides a swappable interface for LLM providers.
The default implementation uses Google's Gemini API.
"""


class BaseLLMProvider:
    """Abstract base class for LLM providers."""
    
    def generate_docstring(
        self,
        entity_type: str,
        name: str,
        signature: str,
        body: str
    ) -> str:
        """
        Generate a docstring for a code entity.
        
        Args:
            entity_type: 'module', 'class', or 'function'
            name: Entity name
            signature: Full signature string
            body: Source code body
        
        Returns:
            Generated docstring text
        
        Raises:
            NotImplementedError: If not implemented by subclass
        """
        raise NotImplementedError("Subclasses must implement generate_docstring")
