import re


def slugify(text):
    """Lowercases text and replaces runs of non-alphanumeric characters with a single hyphen."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
