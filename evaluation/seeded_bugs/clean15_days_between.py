from datetime import date


def days_between(start, end):
    """Returns the number of whole days from start to end, both datetime.date values. Negative if end is earlier."""
    return (end - start).days
