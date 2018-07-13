from typing import List

from mediawords.db.handler import DatabaseHandler
from mediawords.util.log import create_logger
from mediawords.util.perl import decode_object_from_bytes_if_needed

log = create_logger(__name__)


class McPostgresRegexMatch(Exception):
    """postgres_regex_match() exception."""
    pass


def postgres_regex_match(db: DatabaseHandler, strings: List[str], regex: str) -> bool:
    """Run the regex through the PostgreSQL engine against a given list of strings.

    Return True if any string matches the given regex.

    Only try to match against the first megabyte of each string.  Don't try to match on any string that has a null char.

    This is necessary because very occasionally the wrong combination of text and complex boolean regex will cause Perl
    (Python too?) to hang."""

    strings = decode_object_from_bytes_if_needed(strings)
    regex = decode_object_from_bytes_if_needed(regex)

    if not isinstance(strings, list):
        raise McPostgresRegexMatch("Strings must be a list, but is: %s" % str(strings))

    if len(strings) == 0:
        return False

    max_len = 1024 * 1024
    filter_strings = False
    for s in strings:
        if (len(s) > max_len) or ('\x00' in s):
            filter_strings = True
            break

    # do this two pass thing so that we don't unnecessarily copy the whole strings list
    if filter_strings:
        filtered_strings = []
        for s in strings:
            if len(s) > max_len:
                s = s[0:max_len]
            if '\x00' in s:
                s = ''
            filtered_strings.append(s)

        strings = filtered_strings

    if not isinstance(strings[0], str):
        raise McPostgresRegexMatch("Strings must be a list of strings, but is: %s" % str(strings))

    full_regex = '(?isx)%s' % regex
    match = db.query("""
        SELECT 1
        FROM UNNEST(%(strings)s) AS string
        WHERE string ~ %(regex)s
        LIMIT 1
    """, {
        'strings': strings,  # list gets converted to PostgreSQL's ARRAY[]
        'regex': full_regex,
    }).hash()

    if match is not None:
        return True
    else:
        return False
