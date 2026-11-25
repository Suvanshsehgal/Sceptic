def dedupe_keep_order(items):
    """Removes duplicate items and keeps the first occurrence of each, in the original order."""
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
