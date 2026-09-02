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

    @patch('llm.gemini.GeminiDocGenerator.client')
    def test_429_advances_to_next_model(self, mock_client):
        """A 429 from one model should advance to the next model in
        the fallback list, not re-try the same model on the next
        attempt. Each model has its own quota, so re-trying a model
        that just 429'd wastes the attempt."""
        from google.api_core.exceptions import ClientError

        def make_429():
            err = ClientError('429 RESOURCE_EXHAUSTED')
            err.code = 429
            return err

        # First 3 models return 429, fourth succeeds
        mock_client.models.generate_content.side_effect = [
            make_429(),
            make_429(),
            make_429(),
            Mock(text="Success on fourth"),
        ]

        gen = GeminiDocGenerator(api_key='test-key')
        result = gen.generate_docstring(
            entity_type='function',
            name='foo',
            signature='def foo()',
            body='def foo(): pass',
            retry_attempts=1,  # one attempt; should walk the fallback chain
        )

        assert result == "Success on fourth"
        # 4 calls: 3.6, 3.5, 2.5, then flash-latest
        assert mock_client.models.generate_content.call_count == 4
        called_with = [
            call.kwargs['model']
            for call in mock_client.models.generate_content.call_args_list
        ]
        assert called_with[0] == 'gemini-3.6-flash'
        assert called_with[1] == 'gemini-3.5-flash'
        assert called_with[2] == 'gemini-2.5-flash'
        assert called_with[3] == 'gemini-flash-latest'
