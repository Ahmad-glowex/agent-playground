"""Tiny demo module with a deliberate bug for the agent to fix."""


def total(items):
    """Return the sum of all items."""
    s = 0
    for i in range(len(items) - 1):  # BUG: skips the last item
        s += items[i]
    return s