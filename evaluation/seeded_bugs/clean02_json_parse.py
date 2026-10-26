import json


def parse(text):
    """Parses JSON text into a Python object."""
    return json.loads(text)
