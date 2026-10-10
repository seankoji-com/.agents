#!/usr/bin/env python3
"""wordstat: count the words in a text file.

Usage: python3 wordstat.py count FILE
"""
import sys


def count_words(text):
    return len([word for word in text.split(' ') if word])


def main(argv):
    if len(argv) != 3 or argv[1] != 'count':
        print('usage: wordstat.py count FILE', file=sys.stderr)
        return 2
    with open(argv[2]) as stream:
        print(count_words(stream.read()))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
