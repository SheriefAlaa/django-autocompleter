import copy
import re
import unicodedata

from autocompleter import settings


def get_normalized_term(term, dash_replacement=''):
    """
    Convert the term into a basic form that's easier to search.
    1) Force convert from text to unicode if necessary
    2) Make lowercase
    3) Convert to ASCII, switching characters with accents to their non-accented form
    4) Replace & with and
    5) (Optionally) remove dashes
    5) Trim white space off end and beginning
    6) Remove extra spaces
    7) Remove all characters that are not alphanumeric
    """
    if type(term) == str:
        term = term.decode('utf-8')
    term = term.lower()
    term = unicodedata.normalize('NFKD', unicode(term)).encode('ASCII', 'ignore')
    term = term.replace('&', 'and')
    term = term.strip()
    term = term.replace('-', dash_replacement)
    term = re.sub(r'[\s]+', ' ', term)
    term = re.sub(settings.CHARACTER_FILTER, '', term)
    return term


def get_norm_term_variations(term):
    """
    Get variations of a term in formalized form
    """
    norm_terms = [get_normalized_term(term, dash_replacement='')]
    if '-' in term:
        norm_terms.append(get_normalized_term(term, dash_replacement=' '))
    return norm_terms


def get_all_variations(term, phrase_aliases):
    """
    Given the term and dict of phrase to phrase alias mappings,
    return all perumations of term with possible alias phrases substituted
    """
    # We form a stack of different terms we come up with and put each new alias in
    #then keep popping from it until the stack is empty. The stack allows us to
    # alias different parts of already aliased terms
    # ie. US CPI -> United Stats CPI -> United States Consumer Price Index
    term_stack = [term]

    # Term aliases serves to functions:
    # 1) The keys represent each successful term we have.
    # 2) The values are each list of parts of the term that have been aliased to prevent
    # double aliasing... i.e. California -> CA -> Canada.
    term_aliases = {term: []}

    while len(term_stack) != 0:
        # Grab the term
        term = term_stack.pop()
        # Get the ranges that have already been aliased for the term
        aliased_phrase_ranges = term_aliases[term]
        # Get indices of all the phrases in that term
        phrase_map = get_phrase_indices_for_term(term)
        for phrase in phrase_map.keys():
            # If the phrase has defined aliases, we try to replace with it's aliaes
            if phrase in phrase_aliases:
                # Grab alias, and grab the range of words alias wants to replace
                phrase_alias = phrase_aliases[phrase]
                alias_phrase_range = phrase_map[phrase]
                # If any part of the phrase meant to be replaced is itself an alias, then nevermind.
                if term_phrase_already_aliased(alias_phrase_range, aliased_phrase_ranges):
                    continue
                # Otherwise grab the range of words we're about to replace and do the replacing!
                (phrase_start, phrase_end,) = alias_phrase_range
                term_words = term.split()
                term_words[phrase_start:phrase_end] = [phrase_alias]
                term_alias = ' '.join(term_words)
                # If newly aliased term is not a new term, then nevermind...Else can get in endless aliasing loop
                if term_alias in term_aliases:
                    continue
                # Otherwise add new term to stack for further possible aliasing
                term_stack.append(term_alias)
                # And add to dict of aliased terms
                # Aliased phrase ranges of this new term equals the already aliased phrase ranges
                # of the parent term + this newly aliased phrase range
                term_alias_phrase_ranges = copy.copy(aliased_phrase_ranges)
                term_alias_phrase_ranges.append(alias_phrase_range)
                term_aliases[term_alias] = term_alias_phrase_ranges

    if term == 'us consumer price index':
        print term_aliases
    return term_aliases.keys()


def get_phrase_indices_for_term(term):
    """
    For an term, return of index of every phrase in the term to it's
    word position (start word number, end word number,) within the term.

    Note: if a phrase appears twice in a term, then the very last position
    will be recorded. For our purposes, this works because other occurences
    will be handled when this function is called recursively
    """
    words = term.split()
    num_words = len(words)
    phrase_map = {}
    for i in range(0, num_words):
        for j in range(1, num_words + 1):
            if i >= j:
                continue
            phrase = ' '.join(words[i:j])
            phrase_map[phrase] = (i, j,)
    return phrase_map


def term_phrase_already_aliased(alias_phrase_range, aliased_phrase_ranges):
    """
    For the phrase range (start/end word index) that we want to alias, tell us if
    some part of the phrase has already been aliased.
    """
    (alias_phrase_start, alias_phrase_end,) = alias_phrase_range
    for aliased_phrase_range in aliased_phrase_ranges:
        (aliased_phrase_start, aliased_phrase_end,) = aliased_phrase_range
        if alias_phrase_start >= aliased_phrase_start:
            return True
        elif alias_phrase_end <= aliased_phrase_end:
            return True
    return False
