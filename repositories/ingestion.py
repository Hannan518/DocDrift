import os
import tempfile
import shutil
from pathlib import Path
from typing import List

from git import Repo


def clone_github_repo(github_url: str) -> str:
    """
    Clone a GitHub repository (shallow clone for speed).
    
    Args:
        github_url: Full GitHub URL (e.g., https://github.com/user/repo)
    
    Returns:
        Path to the cloned directory
    """
    temp_dir = tempfile.mkdtemp(prefix='docdrift_')
    
    try:
        Repo.clone_from(
            github_url,
            temp_dir,
            depth=1  # Shallow clone for speed
        )
        return temp_dir
    except Exception as e:
        # Clean up on failure
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        raise Exception(f"Failed to clone repository: {str(e)}")


def extract_zip_upload(upload_file) -> str:
    """
    Extract an uploaded zip file to a temporary directory.
    
    Args:
        upload_file: Django FileField or file-like object
    
    Returns:
        Path to the extracted directory
    """
    import zipfile
    
    temp_dir = tempfile.mkdtemp(prefix='docdrift_')
    
    try:
        # Handle Django UploadedFile or regular file
        if hasattr(upload_file, 'read'):
            file_content = upload_file.read()
        else:
            with open(upload_file, 'rb') as f:
                file_content = f.read()
        
        # Write to temp file
        zip_path = os.path.join(temp_dir, 'upload.zip')
        with open(zip_path, 'wb') as f:
            f.write(file_content)
        
        # Extract
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        # Remove the zip file itself
        os.remove(zip_path)
        
        return temp_dir
    except Exception as e:
        # Clean up on failure
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        raise Exception(f"Failed to extract zip file: {str(e)}")


def list_python_files(directory: str) -> List[Path]:
    """
    List all Python files in a directory tree.
    
    Args:
        directory: Path to the directory
    
    Returns:
        List of Path objects for .py files
    """
    return list(Path(directory).rglob('*.py'))


def validate_python_codebase(directory: str) -> tuple[bool, str]:
    """
    Validate that a directory contains Python files.
    
    Args:
        directory: Path to the directory
    
    Returns:
        Tuple of (is_valid, message)
    """
    py_files = list_python_files(directory)
    
    if len(py_files) == 0:
        return False, "No Python files found in the repository"
    
    return True, f"Found {len(py_files)} Python files"


def cleanup_temp_directory(directory: str) -> bool:
    """
    Remove a temporary directory.
    
    Args:
        directory: Path to the directory to remove
    
    Returns:
        True if successful, False otherwise
    """
    try:
        if directory and os.path.exists(directory):
            shutil.rmtree(directory)
            return True
        return False
    except Exception:
        return False
