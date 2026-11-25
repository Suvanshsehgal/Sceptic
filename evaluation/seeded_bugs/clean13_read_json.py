import json
from pathlib import Path


def load_settings(path):
    """Reads a JSON object from a file and returns it as a dict. Raises ValueError if the top level is not an object."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("settings must be a JSON object")
    return data
