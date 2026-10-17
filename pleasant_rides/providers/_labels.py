def unique(labels):
    """Numbers any repeated labels, since the app identifies routes by (provider, label)."""
    counts = {}
    result = []
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
        result.append(label if counts[label] == 1 else f"{label} ({counts[label]})")
    return result
