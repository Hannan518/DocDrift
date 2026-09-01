"""A more complex module for testing various patterns."""

import os
from typing import List, Optional

def function_with_complex_args(
    positional,
    *args,
    keyword_only,
    **kwargs
) -> dict:
    """Function with complex argument patterns."""
    return {}

def function_with_decorators():
    """A function with decorators."""
    pass

class ComplexClass:
    """A class with inheritance and methods."""
    
    class_var = 10
    
    def __init__(self, x: int, y: str = "default"):
        self.x = x
        self.y = y
    
    @property
    def value(self):
        return self.x
    
    def method_with_defaults(self, a, b=None, c="test"):
        return a
    
    def __str__(self):
        return f"ComplexClass({self.x})"
    
    def __repr__(self):
        return self.__str__()

def standalone_function():
    """A standalone function."""
    pass
