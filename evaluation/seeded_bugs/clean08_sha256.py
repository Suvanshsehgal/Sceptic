import hashlib


def file_digest(data):
    """Returns the SHA-256 hex digest of bytes."""
    return hashlib.sha256(data).hexdigest()
