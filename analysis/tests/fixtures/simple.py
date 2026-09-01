"""Simple module with functions and classes for testing."""

def simple_function(x, y):
    """A simple function that adds two numbers."""
    return x + y

def function_with_types(a: int, b: str = "hello") -> str:
    """A function with type hints."""
    return f"{b} {a}"

def function_with_docstring():
    """This function already has a docstring."""
    pass

def private_function():
    """Private function should be skipped by parser."""
    pass

class SimpleClass:
    """A simple class."""
    
    def method(self, x):
        """A simple method."""
        return x * 2
    
    def another_method(self, a, b=10):
        return a + b

class ClassWithInit:
    def __init__(self, name: str, value: int = 0):
        self.name = name
        self.value = value
    
    def get_name(self):
        return self.name
    
    def _private_method(self):
        """Private methods should be skipped."""
        pass

def _private_function():
    """Should be skipped."""
    pass
