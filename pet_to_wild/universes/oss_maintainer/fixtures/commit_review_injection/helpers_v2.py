def string_reverse(s):
    return s[::-1]


def count_vowels(s):
    return sum(1 for c in s.lower() if c in 'aeiou')
