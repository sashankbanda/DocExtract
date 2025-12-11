import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Base paths for input and output folders
BASE_DIR = Path(__file__).parent.parent
INPUT_DIR = BASE_DIR / "input_files"
OUTPUT_DIR = BASE_DIR / "output_files"


def ensure_folders() -> None:
    """Create input_files/ and output_files/ directories if they don't exist."""
    INPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename by removing extension and replacing unsafe characters.
    
    Args:
        filename: Original filename
        
    Returns:
        Safe filename without extension, in snake_case
    """
    # Remove extension
    name = Path(filename).stem
    
    # Replace spaces and unsafe characters with underscores
    name = re.sub(r'[^\w\-_]', '_', name)
    
    # Remove multiple consecutive underscores
    name = re.sub(r'_+', '_', name)
    
    # Remove leading/trailing underscores
    name = name.strip('_')
    
    # Convert to snake_case (lowercase)
    name = name.lower()
    
    return name or "file"


def save_bytes(path: Path, bytes_data: bytes) -> None:
    """
    Save bytes data to a file.
    
    Args:
        path: Full path to save the file
        bytes_data: Bytes data to save
    """
    try:
        ensure_folders()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            f.write(bytes_data)
        logger.info("Saved input file to %s", path)
    except Exception as e:
        logger.error("Failed to save bytes to %s: %s", path, e)
        # Don't raise - file saving should not break the API


def save_json(path: Path, data: Any) -> None:
    """
    Save data as pretty-formatted JSON.
    
    Args:
        path: Full path to save the JSON file
        data: Data to serialize as JSON
    """
    try:
        ensure_folders()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        logger.info("Saved JSON data to %s", path)
    except Exception as e:
        logger.error("Failed to save JSON to %s: %s", path, e)
        # Don't raise - file saving should not break the API


def get_input_path(filename: str, prefix: str = "01") -> Path:
    """
    Get path for input file with prefix.
    
    Args:
        filename: Original filename
        prefix: Two-digit prefix (default: "01")
        
    Returns:
        Path object for the input file
    """
    safe_name = sanitize_filename(filename)
    return INPUT_DIR / f"{prefix}_{safe_name}"


def get_output_path(filename: str, suffix: str, prefix: str, extension: str = "json") -> Path:
    """
    Get path for output file with prefix and suffix.
    
    Args:
        filename: Original filename
        suffix: Suffix to add (e.g., "_text", "_bboxes", "_structured")
        prefix: Two-digit prefix (e.g., "02", "03", "04")
        extension: File extension (default: "json")
        
    Returns:
        Path object for the output file
    """
    safe_name = sanitize_filename(filename)
    extension = extension.lstrip(".")
    return OUTPUT_DIR / f"{prefix}_{safe_name}{suffix}.{extension}"


def save_text(path: Path, text: str) -> None:
    """
    Save text data to a file.
    
    Args:
        path: Full path to save the file
        text: Text content to save
    """
    try:
        ensure_folders()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        logger.info("Saved text file to %s", path)
    except Exception as e:
        logger.error("Failed to save text to %s: %s", path, e)
        # Don't raise - file saving should not break the API

