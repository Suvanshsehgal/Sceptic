def chunks(items, size):
    """Splits a list into consecutive lists of at most size items. The size must be positive."""
    if size <= 0:
        raise ValueError("size must be positive")
    return [items[i:i + size] for i in range(0, len(items), size)]
