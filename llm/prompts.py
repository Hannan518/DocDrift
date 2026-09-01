"""Prompt templates for LLM docstring generation."""


def build_docstring_prompt(
    entity_type: str,
    name: str,
    signature: str,
    body: str
) -> str:
    """
    Build a prompt for generating Google-style docstrings.
    
    Args:
        entity_type: 'module', 'class', or 'function'
        name: Entity name
        signature: Full signature string
        body: Source code body
    
    Returns:
        Formatted prompt string
    """
    return f"""Generate a concise Python docstring in Google style for the following {entity_type}.

Name: {name}
Signature: {signature}

Source code:
{body}

Return ONLY the docstring content (no triple quotes, no code). Include:
- One-line summary
- Args: (for functions/methods, with type hints if clear)
- Returns: (for functions/methods)
- Raises: (if applicable based on code inspection)

Keep it concise and factual based on the actual code."""


def build_module_prompt(
    name: str,
    body: str
) -> str:
    """Build prompt for module-level docstring."""
    return f"""Generate a concise Python docstring for the following module.

Module name: {name}

Source code (first 500 lines):
{body[:2000]}

Return ONLY the docstring content (no triple quotes). Include:
- One-line summary of the module's purpose
- Brief description of main components (if any)

Keep it concise and factual."""


def build_class_prompt(
    name: str,
    signature: str,
    body: str
) -> str:
    """Build prompt for class docstring."""
    return f"""Generate a concise Python docstring in Google style for the following class.

Class name: {name}
Signature: {signature}

Source code:
{body}

Return ONLY the docstring content (no triple quotes). Include:
- One-line summary
- Attributes: (if instance variables are set in __init__)
- Example: (if usage is clear from code)

Keep it concise and factual."""


def build_function_prompt(
    name: str,
    signature: str,
    body: str
) -> str:
    """Build prompt for function/method docstring."""
    return f"""Generate a concise Python docstring in Google style for the following function.

Function name: {name}
Signature: {signature}

Source code:
{body}

Return ONLY the docstring content (no triple quotes). Include:
- One-line summary
- Args: (for each parameter, with type hints if clear)
- Returns: (with type if clear)
- Raises: (if exceptions are raised)

Keep it concise and factual based on the actual code."""
