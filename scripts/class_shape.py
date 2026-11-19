#!/usr/bin/env python3
"""Structural evidence for the class map: the shape of a class.

The bodies of a method say what a class does, but they do not say what kind
of class it is.  A class that keeps its implementation also keeps its shape:
the same methods with the same names, a constructor with the same types and
the same kinds of fields.  The shape is what tells two classes apart when
their bodies are all generic, which happens a lot with the small classes that
only have a constructor.

The shape of the old class is translated to the new side with the reviewed
map, so that the two sides can be compared.  A class has more than one
constructor now and then, so the constructors are compared as a set: the two
classes are alike when the best pair of constructors agrees.
"""
import difflib
import re

METHOD_RE = re.compile(r'^\.method[^\n]*$.*?^\.end method[ \t]*$', re.M | re.S)
CLASS_RE = re.compile(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)', re.M)
FIELD_RE = re.compile(r'^\.field\s+(.*)$', re.M)
PRIMITIVES = {'Z', 'B', 'C', 'D', 'F', 'I', 'J', 'S', 'V'}


def parse_types(descriptor):
    """The types of a parameter list, in the order they are declared.

    A descriptor is a run of single letters for the primitives and of
    ``L<name>;`` for the classes.  The classes keep their semicolon, because
    that is how the map writes them.  Splitting the list on the semicolons
    would run a primitive into the class that follows it, so the list is
    read one type at a time.
    """
    types = []
    index = 0
    length = len(descriptor)
    while index < length:
        start = index
        while descriptor[index] == '[':
            index += 1
        if index >= length:
            break
        if descriptor[index] == 'L':
            end = descriptor.find(';', index)
            if end < 0:
                break
            index = end + 1
            types.append(descriptor[start:index])
        else:
            index += 1
            types.append(descriptor[start:index])
    return tuple(types)


def parse(text):
    """The methods and the fields of a smali file."""
    owner_match = CLASS_RE.search(text)
    owner = owner_match.group(1) if owner_match else None
    methods = []
    for block in METHOD_RE.findall(text):
        header = block.splitlines()[0]
        name = re.search(r'\.method\s+(.*?)\s+([^\s(]+)\(', header)
        if not name:
            continue
        params = re.search(r'\(([^)]*)\)', header)
        # the types keep their semicolon: they are the names of the classes
        # and the map is written with them
        types = parse_types(params.group(1)) if params else ()
        methods.append((name.group(2), types))
    fields = []
    for line in FIELD_RE.findall(text):
        name, _, kind = line.rpartition(':')
        kind = kind.strip()
        if not kind:
            continue
        fields.append((kind, 'static' in line, (kind,)))
    return owner, methods, fields


def translate(tokens, mapping):
    """The names of the types, translated to the other side of the map."""
    result = []
    for token in tokens:
        if token in PRIMITIVES or token.startswith('['):
            result.append(token)
            continue
        result.append(mapping.get(token, token))
    return tuple(result)


def similarity(left, right):
    """How alike two sequences are, between 0 and 1."""
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(None, list(left), list(right),
                                    autojunk=False).ratio()


def shape(class_info, mapping=None):
    """The shape of a class, with the names of the types translated."""
    methods, fields = class_info['methods'], class_info['fields']
    constructors = []
    for name, types in methods:
        if name == '<init>':
            constructors.append(translate(types, mapping) if mapping else types)
    field_types = []
    for _, _, types in fields:
        field_types.append(translate(types, mapping)[0] if mapping else types[0])
    return {
        'constructors': tuple(constructors),
        'methodNames': tuple(sorted(name for name, _ in methods)),
        'methodArities': tuple(sorted(len(types) for _, types in methods)),
        'fieldTypes': tuple(field_types),
    }


def compare(old_shape, new_shape):
    """The score of two shapes, between 0 and 1.

    The constructor counts the most: it is the signature of the class.  The
    fields come next, because they say what the class holds.  The names and
    the arities of the methods come last.
    """
    constructors = pair_score(old_shape['constructors'], new_shape['constructors'])
    fields = similarity(old_shape['fieldTypes'], new_shape['fieldTypes'])
    names = similarity(old_shape['methodNames'], new_shape['methodNames'])
    arities = similarity(old_shape['methodArities'], new_shape['methodArities'])
    return (0.45 * constructors + 0.3 * fields + 0.15 * names + 0.1 * arities)


def pair_score(left, right):
    """The score of two sets of constructors.

    Every constructor of the old class is paired with the constructor of the
    new class that resembles it the most, and each new constructor is used
    once.  The score is the mean of the pairs that were made, and it falls
    when one side has constructors that the other side does not have.
    """
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    pairs = sorted(
        ((similarity(one, two), i, j) for i, one in enumerate(left)
         for j, two in enumerate(right)),
        reverse=True)
    used_left, used_right, total = set(), set(), 0.0
    for value, i, j in pairs:
        if i in used_left or j in used_right:
            continue
        used_left.add(i)
        used_right.add(j)
        total += value
    # a class that has more constructors than the other one keeps the score
    # down: the missing ones are a difference in the shape
    missing = abs(len(left) - len(right))
    return (total / max(len(left), len(right))) * (1.0 - 0.15 * missing)
