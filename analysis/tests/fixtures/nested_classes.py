"""Module with nested classes for testing."""

class OuterClass:
    """An outer class containing an inner class."""
    
    def outer_method(self):
        pass
    
    class InnerClass:
        """An inner class."""
        
        def inner_method(self, x):
            return x + 1

class OuterWithMultipleMethods:
    def method_a(self):
        pass
    
    def method_b(self):
        pass
    
    def method_c(self, arg1, arg2=None):
        """Method with default argument."""
        return arg1
