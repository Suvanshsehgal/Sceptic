from collections import Counter


def word_counts(text):
    """Counts lowercase words separated by whitespace and returns a dict of word to count."""
    return dict(Counter(text.lower().split()))
