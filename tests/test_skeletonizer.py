"""Tests for skeletonizer."""

from context_graph.skeletonizer import skeletonize


def test_simple_function():
    source = '''def foo(x: int) -> str:
    """A docstring."""
    return str(x)
'''
    result = skeletonize(source)
    assert "def foo(x: int) -> str:" in result
    assert '"""A docstring."""' in result
    assert "return str(x)" not in result
    assert "..." in result


def test_function_no_docstring():
    source = '''def bar(x):
    return x + 1
'''
    result = skeletonize(source)
    assert "def bar(x):" in result
    assert "return x + 1" not in result
    assert "..." in result


def test_class_with_methods():
    source = '''class Foo:
    """A class."""

    def method(self) -> str:
        """Method doc."""
        x = 1
        return str(x)

    def other(self):
        pass
'''
    result = skeletonize(source)
    assert "class Foo:" in result
    assert '"""A class."""' in result
    assert "def method(self) -> str:" in result
    assert '"""Method doc."""' in result
    assert "x = 1" not in result
    assert "def other(self):" in result


def test_preserves_decorators():
    source = '''@staticmethod
def helper():
    """Help."""
    do_stuff()
    return 42
'''
    result = skeletonize(source)
    assert "@staticmethod" in result
    assert "def helper():" in result
    assert "do_stuff()" not in result


def test_nested_class():
    source = '''class Outer:
    class Inner:
        def inner_method(self):
            """Inner doc."""
            complex_logic()
            return True
'''
    result = skeletonize(source)
    assert "class Outer:" in result
    assert "class Inner:" in result
    assert "def inner_method(self):" in result
    assert "complex_logic()" not in result
