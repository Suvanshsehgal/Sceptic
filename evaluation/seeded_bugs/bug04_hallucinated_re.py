import re


def find_all_digits(text):
    """Returns every run of digits in text."""
    return re.matchall(r"\d+", text)
