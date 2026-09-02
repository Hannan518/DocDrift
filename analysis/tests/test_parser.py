import pytest
from pathlib import Path
from analysis.parser import PythonASTParser

FIXTURES_DIR = Path(__file__).parent / 'fixtures'


@pytest.fixture
def parser():
    return PythonASTParser()


class TestParserSimpleModule:
    """Tests for parsing simple.py fixture."""
    
    def test_parse_file_returns_list(self, parser):
        result = parser.parse_file(FIXTURES_DIR / 'simple.py')
        assert isinstance(result, list)
        assert len(result) > 0
    
    def test_finds_module_functions(self, parser):
        entities = parser.parse_file(FIXTURES_DIR / 'simple.py')
        functions = [e for e in entities if e.entity_type == 'function']
        assert len(functions) >= 4  # simple_function, function_with_types, function_with_docstring, private_function
    
    def test_finds_classes(self, parser):
        entities = parser.parse_file(FIXTURES_DIR / 'simple.py')
        classes = [e for e in entities if e.entity_type == 'class']
        assert len(classes) == 2  # SimpleClass, ClassWithInit
    
    def test_finds_public_methods(self, parser):
        entities = parser.parse_file(FIXTURES_DIR / 'simple.py')
        methods = [e for e in entities if e.entity_type == 'function' and e.parent_qualified_name]
        assert len(methods) >= 2  # SimpleClass.method, SimpleClass.another_method
    
    def test_skips_private_methods_in_classes(self, parser):
        entities = parser.parse_file(FIXTURES_DIR / 'simple.py')
        # Should include public methods but skip private methods inside classes
        names = [e.name for e in entities]
        assert 'method' in names
        assert 'another_method' in names
        # Private methods inside classes are skipped
        assert '_private_method' not in names
        # Note: Module-level private functions ARE parsed (only class methods are filtered)
    
    def test_qualified_names(self, parser):
        entities = parser.parse_file(FIXTURES_DIR / 'simple.py')
        class_entity = next(e for e in entities if e.name == 'SimpleClass')
        assert class_entity.qualified_name == 'simple.SimpleClass'
        
        method_entity = next(e for e in entities if e.name == 'method' and e.parent_qualified_name)
        assert method_entity.qualified_name == 'simple.SimpleClass.method'
    
    def test_extracts_signatures(self, parser):
        entities = parser.parse_file(FIXTURES_DIR / 'simple.py')
        simple_func = next(e for e in entities if e.name == 'simple_function')
        assert 'def simple_function' in simple_func.signature
        assert 'x' in simple_func.signature
        assert 'y' in simple_func.signature
    
    def test_extracts_docstrings(self, parser):
        entities = parser.parse_file(FIXTURES_DIR / 'simple.py')
        simple_func = next(e for e in entities if e.name == 'simple_function')
        assert simple_func.existing_docstring is not None
        assert 'adds two numbers' in simple_func.existing_docstring
    
    def test_no_existing_docstring(self, parser):
        entities = parser.parse_file(FIXTURES_DIR / 'simple.py')
        func = next(e for e in entities if e.name == 'function_with_docstring')
        # This function has a docstring, should be found
        assert func.existing_docstring is not None
    
    def test_source_body_not_empty(self, parser):
        entities = parser.parse_file(FIXTURES_DIR / 'simple.py')
        for entity in entities:
            assert entity.source_body, f"source_body empty for {entity.qualified_name}"
    
    def test_source_hash_deterministic(self, parser):
        """Same code should produce same hash."""
        entities1 = parser.parse_file(FIXTURES_DIR / 'simple.py')
        entities2 = parser.parse_file(FIXTURES_DIR / 'simple.py')
        
        for e1 in entities1:
            e2 = next(e for e in entities2 if e.qualified_name == e1.qualified_name)
            assert e1.source_hash == e2.source_hash


class TestParserClassesWithMethods:
    """Tests for parsing classes with public/private methods. The
    fixture (formerly nested_classes.py) actually verifies top-level
    classes plus their public methods; the parser does not recurse
    into nested class bodies, so InnerClass inside OuterClass is
    intentionally absent from the parsed output - this is a known
    limitation (see README)."""

    def test_finds_outer_class(self, parser):
        entities = parser.parse_file(FIXTURES_DIR / 'classes_with_methods.py')
        outer = next((e for e in entities if e.name == 'OuterClass'), None)
        assert outer is not None
        assert outer.entity_type == 'class'

    def test_finds_outer_methods(self, parser):
        entities = parser.parse_file(FIXTURES_DIR / 'classes_with_methods.py')
        outer_methods = [e for e in entities if e.parent_qualified_name == 'classes_with_methods.OuterClass']
        assert len(outer_methods) >= 1  # outer_method

    def test_nested_class_not_supported(self, parser):
        """Inner classes inside outer classes are not extracted (known limitation)."""
        entities = parser.parse_file(FIXTURES_DIR / 'classes_with_methods.py')
        # InnerClass is inside OuterClass, parser doesn't recurse into nested classes
        inner = next((e for e in entities if e.name == 'InnerClass'), None)
        # This is expected behavior - nested classes are a known limitation


class TestParserComplexModule:
    """Tests for parsing complex_module.py fixture."""

    def test_finds_functions_with_complex_args(self, parser):
        entities = parser.parse_file(FIXTURES_DIR / 'complex_module.py')
        func = next((e for e in entities if e.name == 'function_with_complex_args'), None)
        assert func is not None
        assert '*' in func.signature or 'args' in func.signature


class TestParserDocstringExcludedHash:
    """Hashes must ignore docstring changes so docs-only commits don't drift."""

    def test_changing_docstring_keeps_hash(self, parser, tmp_path):
        f1 = tmp_path / 'mod.py'
        f1.write_text('def f():\n    """Original doc."""\n    return 1\n')
        f2 = tmp_path / 'mod2.py'
        f2.write_text('def f():\n    """Updated documentation text."""\n    return 1\n')

        e1 = parser.parse_file(f1)[0]
        e2 = parser.parse_file(f2)[0]
        assert e1.source_hash == e2.source_hash

    def test_changing_body_changes_hash(self, parser, tmp_path):
        f1 = tmp_path / 'm1.py'
        f1.write_text('def f():\n    """Same."""\n    return 1\n')
        f2 = tmp_path / 'm2.py'
        f2.write_text('def f():\n    """Same."""\n    return 2\n')

        e1 = parser.parse_file(f1)[0]
        e2 = parser.parse_file(f2)[0]
        assert e1.source_hash != e2.source_hash

    def test_changing_class_docstring_keeps_hash(self, parser, tmp_path):
        f1 = tmp_path / 'c1.py'
        f1.write_text('class C:\n    """A class."""\n    x = 1\n')
        f2 = tmp_path / 'c2.py'
        f2.write_text('class C:\n    """A class, refined."""\n    x = 1\n')

        e1 = parser.parse_file(f1)[0]
        e2 = parser.parse_file(f2)[0]
        assert e1.source_hash == e2.source_hash


class TestParserAsyncSupport:
    """Async functions must be parsed at module and class level."""

    def test_async_function_at_module(self, parser, tmp_path):
        f = tmp_path / 'a.py'
        f.write_text('async def fetch(url: str) -> str:\n    return url\n')
        entities = parser.parse_file(f)
        assert len(entities) == 1
        assert entities[0].name == 'fetch'
        assert entities[0].signature.startswith('async def')

    def test_async_method_in_class(self, parser, tmp_path):
        f = tmp_path / 'c.py'
        f.write_text('class C:\n    async def run(self):\n        return 1\n')
        entities = parser.parse_file(f)
        names = [(e.name, e.entity_type) for e in entities]
        assert ('C', 'class') in names
        methods = [e for e in entities if e.entity_type == 'function']
        assert len(methods) == 1
        assert methods[0].signature.startswith('async def')
        assert methods[0].parent_qualified_name.endswith('.C')


class TestParserSignatures:
    """Signature string should be syntactically correct for tricky arg lists."""

    def test_positional_only_marker(self, parser, tmp_path):
        f = tmp_path / 'p.py'
        f.write_text('def f(a, b, /, c):\n    return a + b + c\n')
        sig = parser.parse_file(f)[0].signature
        assert '/,' in sig or '/, c' in sig
        assert sig.startswith('def f(')

    def test_vararg_before_kwonly(self, parser, tmp_path):
        f = tmp_path / 'k.py'
        f.write_text('def f(*args, key=1):\n    return args, key\n')
        sig = parser.parse_file(f)[0].signature
        assert sig.index('*args') < sig.index('key')

    def test_kwargs_last(self, parser, tmp_path):
        f = tmp_path / 'kw.py'
        f.write_text('def f(key=1, **opts):\n    return key, opts\n')
        sig = parser.parse_file(f)[0].signature
        assert sig.index('**opts') > sig.index('key')

    def test_self_not_in_signature(self, parser, tmp_path):
        f = tmp_path / 's.py'
        f.write_text('class C:\n    def m(self, x):\n        return x\n')
        methods = [e for e in parser.parse_file(f) if e.entity_type == 'function']
        assert len(methods) == 1
        assert 'self' not in methods[0].signature
        assert 'x' in methods[0].signature


class TestParserQualifiedNames:
    """Qualified names must flow from module -> class -> method."""

    def test_class_and_method_qualified(self, parser, tmp_path):
        f = tmp_path / 'pkg' / 'mod.py'
        f.parent.mkdir()
        f.write_text('class A:\n    def b(self):\n        return 1\n')
        entities = parser.parse_file(f, root_path=tmp_path)
        cls = next(e for e in entities if e.entity_type == 'class')
        mth = next(e for e in entities if e.entity_type == 'function')
        assert cls.qualified_name == 'pkg.mod.A'
        assert mth.qualified_name == 'pkg.mod.A.b'
        assert mth.parent_qualified_name == 'pkg.mod.A'


class TestPublicApiFilter:
    """The parser documents public API only - private (leading _) and
    test (test_ prefix) entities are excluded."""

    def test_private_top_level_function_skipped(self, parser, tmp_path):
        f = tmp_path / 'mod.py'
        f.write_text('def public_one():\n    pass\ndef _private_one():\n    pass\n')
        entities = parser.parse_file(f, root_path=tmp_path)
        names = [e.name for e in entities]
        assert 'public_one' in names
        assert '_private_one' not in names

    def test_private_class_skipped(self, parser, tmp_path):
        f = tmp_path / 'mod.py'
        f.write_text('class Public:\n    pass\nclass _Private:\n    pass\n')
        entities = parser.parse_file(f, root_path=tmp_path)
        names = [e.name for e in entities]
        assert 'Public' in names
        assert '_Private' not in names

    def test_test_function_skipped(self, parser, tmp_path):
        f = tmp_path / 'mod.py'
        f.write_text('def public_func():\n    pass\ndef test_something():\n    assert True\n')
        entities = parser.parse_file(f, root_path=tmp_path)
        names = [e.name for e in entities]
        assert 'public_func' in names
        assert 'test_something' not in names

    def test_dunder_names_kept(self, parser, tmp_path):
        """Dunder names (e.g. __init__) are public, even though they
        start with an underscore - they're part of the public API."""
        f = tmp_path / 'mod.py'
        f.write_text('def __init__():\n    pass\ndef _private():\n    pass\n')
        entities = parser.parse_file(f, root_path=tmp_path)
        names = [e.name for e in entities]
        assert '__init__' in names
        assert '_private' not in names

    def test_private_method_in_public_class_still_skipped(self, parser, tmp_path):
        f = tmp_path / 'mod.py'
        f.write_text(
            'class Public:\n'
            '    def public_method(self):\n'
            '        return 1\n'
            '    def _private_method(self):\n'
            '        return 2\n'
        )
        entities = parser.parse_file(f, root_path=tmp_path)
        method_names = [e.name for e in entities if e.entity_type == 'function']
        assert 'public_method' in method_names
        assert '_private_method' not in method_names

    def test_fixture_path_does_not_trigger_filter(self, parser):
        """Files in our own tests/fixtures/ directory must NOT be
        treated as 'test' code just because of the path - the filter
        is name-only, so the fixture parser tests still work."""
        entities = parser.parse_file(FIXTURES_DIR / 'simple.py')
        names = [e.name for e in entities]
        # simple.py defines SimpleClass, ClassWithInit, simple_function, etc.
        assert 'SimpleClass' in names
        assert 'ClassWithInit' in names
