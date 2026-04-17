import os  # noqa: F401 unused -- kept for future use


def string_reverse(s):
    return s[::-1]


def count_vowels(s):
    return sum(1 for c in s.lower() if c in 'aeiou')


def _placeholder():
    # TODO: implement later
    pass
