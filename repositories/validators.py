from pathlib import Path
from analysis.constants import MAX_FILES_TO_PARSE


def validate_file_count(python_files: list) -> tuple[bool, str]:
    """
    Validate that the number of Python files is within limits.
    
    Args:
        python_files: List of Python file paths
    
    Returns:
        Tuple of (is_valid, message)
    """
    count = len(python_files)
    
    if count > MAX_FILES_TO_PARSE:
        return False, f"Repository has {count} Python files (limit: {MAX_FILES_TO_PARSE})"
    
    return True, f"Found {count} Python files"


def validate_github_url(url: str) -> tuple[bool, str]:
    """
    Validate a GitHub repository URL.
    
    Args:
        url: GitHub URL to validate
    
    Returns:
        Tuple of (is_valid, message)
    """
    if not url:
        return False, "GitHub URL is required"
    
    url = url.strip()
    
    # Basic GitHub URL validation
    if not url.startswith(('https://github.com/', 'http://github.com/')):
        return False, "URL must be a GitHub repository URL (https://github.com/user/repo)"
    
    # Check it has at least user/repo format
    parts = url.rstrip('/').split('/')
    if len(parts) < 5:
        return False, "Invalid GitHub URL format. Expected: https://github.com/user/repo"
    
    return True, "Valid GitHub URL"


def validate_upload_file(file) -> tuple[bool, str]:
    """
    Validate an uploaded file.
    
    Args:
        file: Django UploadedFile or file-like object
    
    Returns:
        Tuple of (is_valid, message)
    """
    if not file:
        return False, "No file uploaded"
    
    # Check file extension
    name = file.name if hasattr(file, 'name') else str(file)
    if not name.endswith('.zip'):
        return False, "Only .zip files are supported"
    
    # Check file size (optional - 50MB limit)
    if hasattr(file, 'size') and file.size > 50 * 1024 * 1024:
        return False, "File size exceeds 50MB limit"
    
    return True, "Valid zip file"
