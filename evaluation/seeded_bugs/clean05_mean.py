def mean(values):
    """Returns the arithmetic mean of a non-empty list of numbers."""
    if not values:
        raise ValueError("mean() needs at least one value")
    return sum(values) / len(values)
