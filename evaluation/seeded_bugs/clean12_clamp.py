def clamp(value, low, high):
    """Returns value limited to the closed interval [low, high]. Requires low <= high."""
    if low > high:
        raise ValueError("low must not exceed high")
    return max(low, min(value, high))
