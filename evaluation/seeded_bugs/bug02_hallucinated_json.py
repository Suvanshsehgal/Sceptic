import json


def parse_config(text):
    """Parses a JSON document into a dict."""
    return json.loadz(text)
