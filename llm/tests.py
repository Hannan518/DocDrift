import pytest
from unittest.mock import Mock, patch, MagicMock
from llm.gemini import GeminiDocGenerator
from llm.prompts import build_docstring_prompt, build_class_prompt, build_function_prompt


class TestPrompts:
    """Tests for prompt generation."""
    
    def test_build_docstring_prompt(self):
        prompt = build_docstring_prompt(
            entity_type='function',
            name='add',
            signature='def add(a: int, b: int) -> int',
            body='def add(a, b): return a + b'
        )
        assert 'function' in prompt
        assert 'add' in prompt
        assert 'def add' in prompt
    
    def test_build_class_prompt(self):
        prompt = build_class_prompt(
            name='MyClass',
            signature='class MyClass(Base)',
            body='class MyClass(Base): pass'
        )
        assert 'class' in prompt
        assert 'MyClass' in prompt
    
    def test_build_function_prompt(self):
        prompt = build_function_prompt(
            name='calculate',
            signature='def calculate(x: float) -> float',
            body='def calculate(x): return x * 2'
        )
        assert 'function' in prompt
        assert 'calculate' in prompt


class TestGeminiDocGenerator:
    """Tests for Gemini docstring generator."""
    
    def test_init(self):
        gen = GeminiDocGenerator(api_key='test-key')
        assert gen.api_key == 'test-key'
    
    @patch('llm.gemini.GeminiDocGenerator.client')
    def test_generate_docstring_success(self, mock_client):
        # Mock the response
        mock_response = Mock()
        mock_response.text = "Generated docstring"
        mock_client.models.generate_content.return_value = mock_response
        
        gen = GeminiDocGenerator(api_key='test-key')
        result = gen.generate_docstring(
            entity_type='function',
            name='test_func',
            signature='def test_func()',
            body='def test_func(): pass'
        )
        
        assert result == "Generated docstring"
    
    @patch('llm.gemini.GeminiDocGenerator.client')
    def test_generate_docstring_strips_whitespace(self, mock_client):
        mock_response = Mock()
        mock_response.text = "  Docstring with spaces  "
        mock_client.models.generate_content.return_value = mock_response
        
        gen = GeminiDocGenerator(api_key='test-key')
        result = gen.generate_docstring(
            entity_type='function',
            name='test_func',
            signature='def test_func()',
            body='def test_func(): pass'
        )
        
        assert result == "Docstring with spaces"
    
    @patch('llm.gemini.GeminiDocGenerator.client')
    def test_generate_docstring_model_fallback(self, mock_client):
        # First model fails, second succeeds
        from google.api_core.exceptions import NotFound
        
        mock_client.models.generate_content.side_effect = [
            NotFound("Model not found"),
            Mock(text="Fallback response")
        ]
        
        gen = GeminiDocGenerator(api_key='test-key')
        result = gen.generate_docstring(
            entity_type='function',
            name='test_func',
            signature='def test_func()',
            body='def test_func(): pass'
        )
        
        assert result == "Fallback response"
        assert mock_client.models.generate_content.call_count == 2
