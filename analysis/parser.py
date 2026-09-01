import ast
import hashlib
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ParsedEntity:
    """Represents a parsed Python code entity."""
    
    entity_type: str  # 'module', 'class', 'function'
    name: str
    qualified_name: str
    signature: str
    source_hash: str
    file_path: str
    line_number: int
    parent_qualified_name: Optional[str]
    existing_docstring: Optional[str]
    source_body: str  # For LLM prompt


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
            if isinstance(node, ast.FunctionDef):
                entities.append(self._parse_function(node, module_name, file_path, None))
            elif isinstance(node, ast.ClassDef):
                entities.extend(self._parse_class(node, module_name, file_path))
        
        return entities
    
    def _parse_function(
        self,
        node: ast.FunctionDef,
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
        file_path: Path
    ) -> List[ParsedEntity]:
        """Parse a class definition and its methods."""
        qualified_name = f"{parent_name}.{node.name}"
        entities = []
        
        # Add the class itself
        entities.append(ParsedEntity(
            entity_type='class',
            name=node.name,
            qualified_name=qualified_name,
            signature=self._extract_class_signature(node),
            source_hash=self._compute_hash(node),
            file_path=str(file_path),
            line_number=node.lineno,
            parent_qualified_name=parent_name,
            existing_docstring=ast.get_docstring(node),
            source_body=ast.unparse(node),
        ))
        
        # Add public methods (skip private methods starting with _)
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                if not item.name.startswith('_'):
                    entities.append(self._parse_function(
                        item,
                        qualified_name,
                        file_path,
                        qualified_name
                    ))
        
        return entities
    
    def _extract_signature(self, node: ast.FunctionDef) -> str:
        """Extract function signature string."""
        args = node.args
        
        # Build signature parts
        parts = []
        
        # Filter out self/cls
        all_args = args.args
        filtered_args = [a for a in all_args if a.arg not in ('self', 'cls')]
        has_self = len(all_args) != len(filtered_args)
        
        # Positional args with defaults
        num_filtered = len(filtered_args)
        num_defaults = len(args.defaults)
        defaults_offset = num_filtered - num_defaults
        
        for i, arg in enumerate(filtered_args):
            annotation = ast.unparse(arg.annotation) if arg.annotation else ''
            arg_str = f"{arg.arg}: {annotation}" if annotation else arg.arg
            
            # Apply default if applicable
            default_idx = i - defaults_offset
            if default_idx >= 0:
                default_val = ast.unparse(args.defaults[default_idx])
                arg_str = f"{arg_str}={default_val}"
            
            parts.append(arg_str)
        
        # Keyword-only args
        for arg in args.kwonlyargs:
            annotation = ast.unparse(arg.annotation) if arg.annotation else ''
            if annotation:
                parts.append(f"{arg.arg}: {annotation}")
            else:
                parts.append(arg.arg)
        
        # Return annotation
        return_annotation = ''
        if node.returns:
            return_annotation = f" -> {ast.unparse(node.returns)}"
        
        # Varargs and kwargs
        if args.vararg:
            parts.append(f"*{args.vararg.arg}")
        if args.kwarg:
            parts.append(f"**{args.kwarg.arg}")
        
        return f"def {node.name}({', '.join(parts)}){return_annotation}"
    
    def _extract_class_signature(self, node: ast.ClassDef) -> str:
        """Extract class signature with base classes."""
        bases = [ast.unparse(base) for base in node.bases]
        if bases:
            return f"class {node.name}({', '.join(bases)})"
        return f"class {node.name}"
    
    def _compute_hash(self, node) -> str:
        """Compute SHA256 hash of normalized node body."""
        source = ast.unparse(node)
        # Normalize: remove docstring, collapse whitespace
        lines = source.split('\n')
        normalized = '\n'.join(line.strip() for line in lines if line.strip())
        return hashlib.sha256(normalized.encode()).hexdigest()
