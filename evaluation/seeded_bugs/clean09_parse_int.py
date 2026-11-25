def parse_port(text):
    """Parses a TCP port number from a string and returns it as an int between 1 and 65535."""
    port = int(text)
    if not 1 <= port <= 65535:
        raise ValueError(f"port out of range: {port}")
    return port
