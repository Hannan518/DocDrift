import ast
import copy
import hashlib
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ParsedEntity:
    """Represents a parsed Python code entity."""

    entity_type: str  # 'class', 'function'
    name: str
    qualified_name: str
    signature: str
    source_hash: str
    file_path: str
    line_number: int
    parent_qualified_name: Optional[str]
    existing_docstring: Optional[str]
    source_body: str  # For LLM prompt


def _is_string_expr(node) -> bool:
    """True for bare string expressions (docstrings / no-op string statements)."""
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
        and isinstance(node.value.value, str)


def _is_public_entity(name: str) -> bool:
    """Whether an entity is part of the public API surface.

    Public = not a private/internal helper (leading underscore) and not
    a test. Tests are detected by:
      - name starting with test_ (a test function or method)
      - class name ending in Test, TestCase, or Tests (a test class)
    Dunder names (`__init__`, `__all__`, etc.) are always treated as
    public so package entry points are documented. This is a name-only
    rule - we don't filter on file paths, since the user submitted the
    repo and may want any file documented.
    """
    if name.startswith('test_') and not name.startswith('test___'):
        return False
    if name.startswith('_') and not (name.startswith('__') and name.endswith('__')):
        return False
    # Test class detection. Strip the trailing "s" on "Tests" so we
    # don't accidentally match legitimate class names like "BetaTests"
    # - the user can rename those.
    if name.endswith('TestCase') or name.endswith('Test'):
        return False
    return True


class PythonASTParser:
    """AST-based Python code parser."""

    def parse_directory(self, root_path: Path) -> List[ParsedEntity]:
        """Parse all Python files in a directory tree."""
        entities = []
        for py_file in root_path.rglob('*.py'):
            try:
                entities.extend(self.parse_file(py_file))
            except SyntaxError:
                continue
        return entities

    def parse_file(self, file_path: Path, root_path: Path = None) -> List[ParsedEntity]:
        """Parse a single Python file."""
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()

        tree = ast.parse(source)

        # Use relative path to avoid duplicate qualified names (e.g., multiple __init__.py)
        if root_path and root_path in file_path.parents:
            rel = file_path.relative_to(root_path)
            module_name = str(rel).replace('/', '.').replace('\\', '.')
            if module_name.endswith('.py'):
                module_name = module_name[:-3]
            if module_name.endswith('.__init__'):
                module_name = module_name[:-9]
        else:
            module_name = file_path.stem

        entities = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _is_public_entity(node.name):
                    entities.append(self._parse_function(node, module_name, file_path, None))
            elif isinstance(node, ast.ClassDef):
                if _is_public_entity(node.name):
                    entities.extend(self._parse_class(node, module_name, file_path, None))

        return entities

    def _parse_function(
        self,
        node,
        parent_name: str,
        file_path: Path,
        parent_qualified: Optional[str]
    ) -> ParsedEntity:
        """Parse a function or method definition."""
        qualified_name = f"{parent_name}.{node.name}"

        return ParsedEntity(
            entity_type='function',
            name=node.name,
            qualified_name=qualified_name,
            signature=self._extract_signature(node),
            source_hash=self._compute_hash(node),
            file_path=str(file_path),
            line_number=node.lineno,
            parent_qualified_name=parent_qualified,
            existing_docstring=ast.get_docstring(node),
            source_body=ast.unparse(node),
        )

    def _parse_class(
        self,
        node: ast.ClassDef,
        parent_name: str,
        file_path: Path,
        parent_qualified: Optional[str]
    ) -> List[ParsedEntity]:
        """Parse a class definition and its public methods."""
        qualified_name = f"{parent_name}.{node.name}"
        entities = []

        # Skip the class entirely if it isn't part of the public API
        # (private name or test class). Without this, a TestCase class
        # itself leaks in even though its test_* methods would be
        # filtered below.
        if not _is_public_entity(node.name):
            return entities

        # Add the class itself
        entities.append(ParsedEntity(
            entity_type='class',
            name=node.name,
            qualified_name=qualified_name,
            signature=self._extract_class_signature(node),
            source_hash=self._compute_hash(node),
            file_path=str(file_path),
            line_number=node.lineno,
            parent_qualified_name=parent_qualified,
            existing_docstring=ast.get_docstring(node),
            source_body=ast.unparse(node),
        ))

        # Add public methods (skip private/dunder methods starting with _,
        # and test_ methods - they're tests, not public API)
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _is_public_entity(item.name):
                    entities.append(self._parse_function(
                        item,
                        qualified_name,
                        file_path,
                        qualified_name
                    ))

        return entities

    def _extract_signature(self, node) -> str:
        """Extract a syntactically correct signature string for a function/method."""
        a = node.args

        posonly = list(a.posonlyargs)
        regular = list(a.args)

        # Drop the leading self/cls (methods)
        if posonly and posonly[0].arg in ('self', 'cls'):
            posonly = posonly[1:]
        elif not posonly and regular and regular[0].arg in ('self', 'cls'):
            regular = regular[1:]

        pos = posonly + regular
        n = len(pos)
        d = len(a.defaults)

        def format_arg(arg, default=None):
            text = arg.arg
            if arg.annotation:
                text += f": {ast.unparse(arg.annotation)}"
            if default is not None:
                text += f"={default}"
            return text

        parts = []
        for i, arg in enumerate(pos):
            default = ast.unparse(a.defaults[d - n + i]) if i >= n - d else None
            parts.append(format_arg(arg, default))

        if posonly:
            parts.insert(len(posonly), '/')

        if a.vararg:
            vararg = f"*{a.vararg.arg}"
            if a.vararg.annotation:
                vararg += f": {ast.unparse(a.vararg.annotation)}"
            parts.append(vararg)
        elif a.kwonlyargs:
            parts.append('*')

        for arg, kw_default in zip(a.kwonlyargs, a.kw_defaults):
            parts.append(format_arg(arg, ast.unparse(kw_default) if kw_default is not None else None))

        if a.kwarg:
            kwarg = f"**{a.kwarg.arg}"
            if a.kwarg.annotation:
                kwarg += f": {ast.unparse(a.kwarg.annotation)}"
            parts.append(kwarg)

        prefix = 'async def' if isinstance(node, ast.AsyncFunctionDef) else 'def'
        return_annotation = f" -> {ast.unparse(node.returns)}" if node.returns else ''

        return f"{prefix} {node.name}({', '.join(parts)}){return_annotation}"

    def _extract_class_signature(self, node: ast.ClassDef) -> str:
        """Extract class signature with base classes."""
        bases = [ast.unparse(base) for base in node.bases]
        keywords = [f"{kw.arg}={ast.unparse(kw.value)}" if kw.arg else f"**{ast.unparse(kw.value)}"
                    for kw in node.keywords]
        all_bases = bases + keywords
        if all_bases:
            return f"class {node.name}({', '.join(all_bases)})"
        return f"class {node.name}"

    def _unparse_without_own_docstring(self, node) -> str:
        """Unparse a node with its own (first-statement) docstring removed."""
        if not (node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)):
            return ast.unparse(node)
        stripped = copy.deepcopy(node)
        stripped.body = stripped.body[1:] or [ast.Pass()]
        return ast.unparse(stripped)

    def _compute_hash(self, node) -> str:
        """
        Compute SHA256 hash of the entity's code, excluding documentation.

        Docstrings are stripped so that docs-only commits never change the
        hash (and never create false drift). For classes, method bodies are
        excluded as well - methods are separate entities with their own
        hashes - so only class-level code (attributes, bases) affects it.
        """
        if isinstance(node, ast.ClassDef):
            segments = [ast.unparse(base) for base in node.bases]
            segments += [f"{kw.arg}={ast.unparse(kw.value)}" for kw in node.keywords if kw.arg]
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if _is_string_expr(item):
                    continue  # the class docstring
                segments.append(ast.unparse(item))
        else:
            segments = [self._unparse_without_own_docstring(node)]

        normalized = '\n'.join(s.strip() for s in segments if s.strip())
        return hashlib.sha256(normalized.encode()).hexdigest()
