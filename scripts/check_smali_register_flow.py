#!/usr/bin/env python3
"""Reject methods whose dex verification would fail on an undefined register.

The dex verifier tracks a type for every 32-bit register unit.  A register that
is read on a path where it was never written has the type ``Undefined``, and
ART refuses to load the class:

    java.lang.VerifyError: Verifier rejected class uc0: jc0 uc0.k() failed to
    verify: jc0 uc0.k(): [0x19] tried to get class from non-reference register
    v1 (type=Undefined)

The existing static checkers are all syntactic: they verify that labels
resolve, that ``move-result`` follows its ``invoke``, that branch offsets are
non-zero, that every symbol reference exists and that the argument types of a
call match the callee.  None of them looks at the control flow graph, so a
handoff that moves an initialization behind a branch join - which leaves one
path without the value - passes every check and only fails on the device.

This checker performs the data flow analysis the dex verifier performs:

  * every method is turned into an instruction graph (branches, switch and
    array payloads, and annotation blocks excluded),
  * the reachable instructions are marked,
  * the set of definitely assigned registers is propagated over the graph,
    merging the predecessor sets by intersection, exactly like the verifier
    merges the register types,
  * an exception handler starts from an empty set, because the verifier
    resets the register state when it enters a handler,
  * a 64-bit value occupies two register units, so a wide write defines both
    units and a wide read requires both.

A register that is read at a reachable instruction without being assigned on
every path is reported.
"""
import argparse
import re
from pathlib import Path

METHOD_RE = re.compile(r'^\.method[^\n]*$.*?^\.end method[ \t]*$', re.M | re.S)
LOCAL_RE = re.compile(r'^\s*\.(locals|registers)\s+(\d+)')
CATCH_RE = re.compile(r'^\s*\.catch(?:all)?\b')
PACKED_RE = re.compile(r'^\s*\.packed-switch\b')
SPARSE_RE = re.compile(r'^\s*\.sparse-switch\b')
ARRAY_DATA_RE = re.compile(r'^\s*\.array-data\b')
ANNOTATION_RE = re.compile(r'^\s*\.(?:sub)?annotation\b')
END_ANNOTATION_RE = re.compile(r'^\s*\.end\s+(?:sub)?annotation\b')
END_ARRAY_DATA_RE = re.compile(r'^\s*\.end\s+array-data\b')
TARGET_RE = re.compile(r':\s*([A-Za-z_][A-Za-z0-9_$]*)')

MOVE_OPS = {
    'move', 'move/from16', 'move/16', 'move-wide', 'move-wide/from16',
    'move-wide/16', 'move-object', 'move-object/from16', 'move-object/16',
}
RESULT_OPS = {'move-result', 'move-result-wide', 'move-result-object',
              'move-exception'}
BRANCH_OPS = {
    'if-eq', 'if-ne', 'if-lt', 'if-ge', 'if-gt', 'if-le',
    'if-eqz', 'if-nez', 'if-ltz', 'if-gez', 'if-gtz', 'if-lez',
}
RETURN_OPS = {'return', 'return-object', 'return-wide', 'return-void'}
WIDE_DEST_OPS = {
    'move-wide', 'move-wide/from16', 'move-wide/16', 'move-result-wide',
    'const-wide', 'const-wide/16', 'const-wide/32', 'const-wide/high16',
    'iget-wide', 'sget-wide', 'aget-wide',
}
# (destination is wide, source is wide) for the conversion opcodes.
CONVERSIONS = {
    'int-to-byte': (False, False), 'int-to-char': (False, False),
    'int-to-short': (False, False), 'int-to-float': (False, False),
    'int-to-long': (True, False), 'int-to-double': (True, False),
    'long-to-int': (False, True), 'long-to-float': (False, True),
    'long-to-double': (True, True),
    'float-to-int': (False, False), 'float-to-long': (True, False),
    'float-to-double': (True, False),
    'double-to-int': (False, True), 'double-to-long': (True, True),
    'double-to-float': (False, True),
}
UNARY_OPS = {'neg-int', 'neg-long', 'neg-float', 'neg-double',
             'not-int', 'not-long'}
# Comparisons whose two sources are 64-bit units.
WIDE_CMP_OPS = {'cmp-long', 'cmpg-double', 'cmpl-double'}
BINARY_PREFIXES = ('add-', 'sub-', 'mul-', 'div-', 'rem-', 'and-', 'or-',
                   'xor-', 'shl-', 'shr-', 'ushr-', 'rsub-')


def regs_in(text):
    return re.findall(r'\b[vp]\d+\b', text)


def partner(register):
    """The second 32-bit unit of a wide value held in register."""
    return register[0] + str(int(register[1:]) + 1)


def expand(register, wide):
    if not wide:
        return [register]
    return [register, partner(register)]


def brace_regs(instruction):
    """The registers of an argument list, expanding a ``v0 .. v7`` range."""
    match = re.search(r'\{([^}]*)\}', instruction)
    if not match:
        return []
    inner = match.group(1)
    span = re.search(r'([vp]\d+)\s*\.\.\s*([vp]\d+)', inner)
    if span:
        first, last = span.group(1), span.group(2)
        start, end = int(first[1:]), int(last[1:])
        if start > end:
            start, end = end, start
        return [first[0] + str(index) for index in range(start, end + 1)]
    return regs_in(inner)


def operands_of(rest):
    """The register operands of an instruction, without its type reference.

    A field or method name may itself look like a register (``->v0:``), so the
    trailing ``Ltype;->member`` reference is dropped before the registers are
    collected.  ``invoke`` instructions list their registers inside braces and
    are handled by :func:`brace_regs` instead.
    """
    head = re.split(r'\s+[L\[]', rest, maxsplit=1)[0]
    return regs_in(head)


def parameter_count(signature):
    """The number of declared parameter registers of a method."""
    start = signature.find('(')
    end = signature.find(')', start + 1)
    if start < 0 or end < 0:
        return 0
    words = 0
    index = start + 1
    while index < end:
        char = signature[index]
        if char == 'L':
            semicolon = signature.find(';', index)
            if semicolon < 0:
                break
            index = semicolon + 1
            words += 1
        elif char in 'JD':
            words += 2
            index += 1
        elif char == '[':
            index += 1
        else:
            words += 1
            index += 1
    return words


def classify(instruction):
    """Return (registers written, registers read) for one instruction."""
    parts = instruction.split(None, 1)
    opcode = parts[0]
    rest = parts[1] if len(parts) > 1 else ''

    if opcode.startswith('invoke') or opcode.startswith('filled-new-array'):
        return [], brace_regs(instruction)

    registers = operands_of(rest)

    if opcode in MOVE_OPS:
        wide = opcode.startswith('move-wide')
        return expand(registers[0], wide), expand(registers[1], wide)
    if opcode in RESULT_OPS:
        wide = opcode == 'move-result-wide'
        return expand(registers[0], wide), []
    if opcode.startswith('const'):
        wide = opcode.startswith('const-wide')
        return expand(registers[0], wide), []
    if opcode == 'new-instance':
        return [registers[0]], []
    if opcode == 'new-array':
        return [registers[0]], expand(registers[1], False)
    if opcode.startswith('sget'):
        wide = opcode.endswith('-wide')
        return expand(registers[0], wide), []
    if opcode.startswith('sput'):
        wide = opcode.endswith('-wide')
        return [], expand(registers[0], wide)
    if opcode.startswith('iget'):
        wide = opcode.endswith('-wide')
        return expand(registers[0], wide), expand(registers[1], False)
    if opcode.startswith('iput'):
        wide = opcode.endswith('-wide')
        return [], [expand(registers[0], wide)[0], registers[1]] \
            if not wide else expand(registers[0], True) + [registers[1]]
    if opcode.startswith('aget'):
        wide = opcode.endswith('-wide')
        return expand(registers[0], wide), \
            expand(registers[1], False) + expand(registers[2], False)
    if opcode.startswith('aput'):
        wide = opcode.endswith('-wide')
        return [], expand(registers[0], wide) + \
            expand(registers[1], False) + expand(registers[2], False)
    if opcode == 'array-length':
        return [registers[0]], expand(registers[1], False)
    if opcode == 'instance-of':
        return [registers[0]], expand(registers[1], False)
    if opcode == 'check-cast':
        return [registers[0]], expand(registers[0], False)
    if opcode in BRANCH_OPS:
        return [], [registers[0]]
    if opcode.startswith('goto'):
        return [], []
    if opcode in RETURN_OPS:
        if not registers:
            return [], []
        wide = opcode == 'return-wide'
        return [], expand(registers[0], wide)
    if opcode == 'throw':
        return [], expand(registers[0], False)
    if opcode.startswith('monitor-'):
        return [], expand(registers[0], False)
    if opcode in ('packed-switch', 'sparse-switch'):
        return [], expand(registers[0], False)
    if opcode == 'fill-array-data':
        return [], expand(registers[0], False)
    if opcode in WIDE_DEST_OPS:
        return expand(registers[0], True), []
    if opcode in UNARY_OPS:
        wide = opcode in ('neg-long', 'neg-double', 'not-long')
        return expand(registers[0], wide), expand(registers[1], wide)
    if opcode in CONVERSIONS:
        dest_wide, source_wide = CONVERSIONS[opcode]
        return expand(registers[0], dest_wide), expand(registers[1], source_wide)
    if opcode in WIDE_CMP_OPS:
        return [registers[0]], expand(registers[1], True) + \
            expand(registers[2], True)
    if opcode.startswith('cmp'):
        # cmpg-float / cmpl-float operate on single width units.
        return [registers[0]], expand(registers[1], False) + \
            expand(registers[2], False)
    for prefix in BINARY_PREFIXES:
        if opcode.startswith(prefix):
            base = opcode.split('/')[0]
            wide = base.endswith('-long') or base.endswith('-double')
            # The shift amount of shl/shr/ushr is a single width int even when
            # the value being shifted is 64 bit.
            shift = base.startswith(('shl-', 'shr-', 'ushr-'))
            if len(registers) >= 3:
                return expand(registers[0], wide), \
                    expand(registers[1], wide) + \
                    expand(registers[2], wide and not shift)
            if opcode.endswith('/2addr'):
                # /2addr form: the destination doubles as the first source.
                return expand(registers[0], wide), \
                    expand(registers[0], wide) + \
                    expand(registers[1], wide and not shift)
            # Immediate forms (lit8, lit16 and rsub-int): destination and a
            # single register source, the third operand is a literal.
            if len(registers) >= 2:
                return expand(registers[0], wide), expand(registers[1], wide)
            return expand(registers[0], wide), []
    return [], []


class Method:
    """The parsed control flow graph of one Smali method."""

    def __init__(self):
        self.ops = []
        self.codes = []
        self.dest = []
        self.reads = []
        self.labels = {}
        self.payload_cases = {}
        self.payload_next = {}
        self.handler_ranges = {}
        self.always = set()


def _skip_block(body, start, end_re):
    """Return the index after the directive block that starts at start."""
    cursor = start
    while cursor < len(body) and not end_re.match(body[cursor]):
        cursor += 1
    return min(cursor + 1, len(body))


def _payload_cases(body, start):
    """The case labels of the switch payload whose directive starts at start."""
    cursor = start
    while cursor < len(body) and not body[cursor].strip():
        cursor += 1
    if cursor >= len(body):
        return [], cursor
    if PACKED_RE.match(body[cursor]):
        cursor += 1
        while cursor < len(body) and not body[cursor].strip():
            cursor += 1
        if cursor >= len(body):
            return [], cursor
        try:
            count = int(body[cursor].strip().split()[0])
        except (ValueError, IndexError):
            return [], cursor + 1
        cursor += 1
        cases = []
        for _ in range(count):
            while cursor < len(body) and not body[cursor].strip():
                cursor += 1
            if cursor >= len(body):
                break
            cases.append(body[cursor].strip().lstrip(':').split()[0])
            cursor += 1
        return cases, cursor
    if SPARSE_RE.match(body[cursor]):
        cursor += 1
        cases = []
        while cursor < len(body):
            text = body[cursor].strip()
            if not text:
                cursor += 1
                continue
            found = re.match(r'^(\S+)\s*->\s*:(\S+)$', text)
            if not found:
                break
            cases.append(found.group(2))
            cursor += 1
        return cases, cursor
    return [], cursor


def _payload_label(body, index):
    """If body[index] starts a payload, return (payload label, next index)."""
    stripped = body[index].strip()
    if not stripped.startswith(':'):
        return None, index
    name = stripped[1:].split()[0] if len(stripped) > 1 else ''
    if not name:
        return None, index
    look = index + 1
    while look < len(body) and (not body[look].strip()
                                or body[look].strip().startswith('#')):
        look += 1
    if look >= len(body):
        return None, index
    if PACKED_RE.match(body[look]) or SPARSE_RE.match(body[look]):
        _cases, end = _payload_cases(body, look + 1)
        return name, end
    if ARRAY_DATA_RE.match(body[look]):
        return name, _skip_block(body, look, END_ARRAY_DATA_RE)
    return None, index


def parse_method(block):
    lines = block.splitlines()
    header = lines[0].strip()
    body = lines[1:-1]
    method = Method()

    registers_count = 0
    registers_directive = None
    for line in body:
        match = LOCAL_RE.match(line)
        if match:
            registers_directive = match.group(1)
            registers_count = int(match.group(2))
            break

    # Index the switch payloads so their case labels can be resolved.
    index = 0
    while index < len(body):
        name, end = _payload_label(body, index)
        if name is not None:
            cursor = index + 1
            while cursor < len(body) and not body[cursor].strip():
                cursor += 1
            cases, _ = _payload_cases(body, cursor + 1)
            method.payload_cases[name] = cases
            index = end
            continue
        index += 1

    # Build the instruction stream.
    index = 0
    while index < len(body):
        stripped = body[index].strip()
        if not stripped or stripped.startswith('#'):
            index += 1
            continue
        if ANNOTATION_RE.match(stripped):
            index = _skip_block(body, index, END_ANNOTATION_RE)
            continue
        if stripped.startswith(':'):
            name, end = _payload_label(body, index)
            if name is not None:
                index = end
                continue
            label = stripped[1:].split()[0]
            if label and label not in method.labels:
                method.labels[label] = len(method.ops)
            index += 1
            continue
        if stripped.startswith('.'):
            if CATCH_RE.match(stripped):
                # .catch Ltype; {:start .. :end} :handler
                # .catchall {:start .. :end} :handler
                found = re.search(r'\{:(\S+?)\s+\.\.\s+:(\S+?)\}\s+:(\S+)', stripped)
                if found:
                    start, end, handler = found.groups()
                    method.handler_ranges.setdefault(handler, []).append(
                        (start, end))
            index += 1
            continue

        parts = stripped.split(None, 1)
        opcode = parts[0]
        dest, reads = classify(stripped)
        method.ops.append(opcode)
        method.codes.append(stripped)
        method.dest.append(dest)
        method.reads.append(reads)

        if opcode in ('packed-switch', 'sparse-switch'):
            found = TARGET_RE.findall(stripped)
            if found:
                method.payload_cases.setdefault(found[-1], [])
        if opcode == 'fill-array-data':
            found = TARGET_RE.findall(stripped)
            if found:
                method.payload_next[found[-1]] = len(method.ops)
        index += 1

    # The parameters are assigned on entry.  An instance method also receives
    # "this" in p0, so the declared parameters start at p1 there.  The local
    # registers start out undefined; the parameters are reachable both through
    # the p-notation and through their v-notation alias.
    declared = parameter_count(header)
    is_static = ' static ' in ' ' + header + ' '
    total = declared if is_static else declared + 1
    for index in range(total):
        method.always.add('p' + str(index))
    if registers_count and total:
        base = (registers_count - total if registers_directive == 'registers'
                else registers_count)
        for index in range(total):
            method.always.add('v' + str(base + index))
    return method


def successors(method, index):
    opcode = method.ops[index]
    code = method.codes[index]
    if opcode in RETURN_OPS or opcode == 'throw':
        return []
    if opcode.startswith('goto'):
        found = TARGET_RE.findall(code)
        if found and found[0] in method.labels:
            return [method.labels[found[0]]]
        return []
    if opcode in BRANCH_OPS:
        found = []
        target = TARGET_RE.findall(code)
        if target and target[0] in method.labels:
            found.append(method.labels[target[0]])
        if index + 1 < len(method.ops):
            found.append(index + 1)
        return found
    if opcode in ('packed-switch', 'sparse-switch'):
        target = TARGET_RE.findall(code)
        found = []
        if target:
            for case in method.payload_cases.get(target[0], []):
                if case in method.labels:
                    found.append(method.labels[case])
        return found
    if opcode == 'fill-array-data':
        target = TARGET_RE.findall(code)
        if target:
            position = method.payload_next.get(target[0])
            if position is not None:
                return [position]
        return []
    if index + 1 < len(method.ops):
        return [index + 1]
    return []


def can_throw(opcode):
    """Whether an opcode can transfer control to an exception handler.

    The verifier merges the register state of a catch handler only from the
    instructions of the try range that can actually throw: a ``return`` or a
    ``goto`` inside the range never enters the handler, so its register state
    - which may lack a value the handler needs - must not constrain the
    handler entry.  Arithmetic other than division and remainder cannot throw
    either; division raises ArithmeticException and is treated as throwing.
    """
    if opcode in ('nop', 'move-exception', 'instance-of'):
        return False
    if opcode.startswith(('move', 'const', 'goto', 'if-', 'return')):
        return False
    if opcode.startswith(('add-', 'sub-', 'mul-', 'and-', 'or-', 'xor-',
                          'shl-', 'shr-', 'ushr-', 'rsub-', 'neg-', 'not-',
                          'cmp', 'int-to-', 'long-to-', 'float-to-',
                          'double-to-')):
        return False
    return True


def analyze(block):
    """Return the findings of one method block."""
    method = parse_method(block)
    count = len(method.ops)
    if not count:
        return [], method

    edges = [successors(method, index) for index in range(count)]
    predecessors = [[] for _ in range(count)]
    for index in range(count):
        for target in edges[index]:
            if 0 <= target < count:
                predecessors[target].append(index)

    # An exception handler is entered from its try ranges: the verifier merges
    # the register state of every instruction inside the range, exactly like it
    # does when an exception unwinds to the handler.
    handler_positions = {}
    covering = [[] for _ in range(count)]
    for handler, ranges in method.handler_ranges.items():
        position = method.labels.get(handler)
        if position is None:
            continue
        handler_positions[position] = ranges
        for start_label, end_label in ranges:
            start = method.labels.get(start_label)
            end = method.labels.get(end_label)
            if start is None or end is None:
                continue
            for covered in range(max(0, start), min(end, count)):
                covering[covered].append(position)

    # Mark the reachable instructions.  The handlers are roots because an
    # exception can transfer control to them from their try range.
    reachable = [False] * count
    stack = [0] + sorted(handler_positions)
    while stack:
        index = stack.pop()
        if index < 0 or index >= count or reachable[index]:
            continue
        reachable[index] = True
        stack.extend(edges[index])

    def handler_state(position):
        """The merged register state of the try ranges of one handler.

        Only the instructions that can throw contribute: the register state of
        a ``return`` or a ``goto`` inside the range never reaches the handler.
        While a throwing instruction of the range has no state yet the handler
        waits, so a provisional value can never degrade the fixpoint.
        """
        incoming = []
        fallback = []
        pending_throwing = False
        for start_label, end_label in handler_positions[position]:
            start = method.labels.get(start_label)
            end = method.labels.get(end_label)
            if start is None or end is None:
                continue
            for covered in range(max(0, start), min(end, count)):
                if not reachable[covered]:
                    continue
                throwing = can_throw(method.ops[covered])
                if out_state[covered] is None:
                    if throwing:
                        pending_throwing = True
                    continue
                if throwing:
                    incoming.append(out_state[covered])
                else:
                    fallback.append(out_state[covered])
        if not incoming:
            if pending_throwing:
                return None
            incoming = fallback
        if not incoming:
            return None
        merged = set(incoming[0])
        for other in incoming[1:]:
            merged &= other
        return merged

    # Propagate the definitely assigned registers.  The entry state of the
    # method holds the parameters, a handler holds the merged state of its try
    # ranges, and every other instruction intersects its predecessors.
    in_state = [None] * count
    out_state = [None] * count
    in_state[0] = set(method.always)
    pending = list(range(count)) + sorted(handler_positions)
    while pending:
        index = pending.pop()
        if not reachable[index]:
            continue
        if index in handler_positions:
            current = handler_state(index)
            if current is None:
                continue
        elif index == 0:
            current = set(method.always)
        else:
            incoming = [out_state[source] for source in predecessors[index]
                        if reachable[source] and out_state[source] is not None]
            if not incoming:
                continue
            merged = set(incoming[0])
            for other in incoming[1:]:
                merged &= other
            current = merged
        if in_state[index] == current and out_state[index] is not None:
            continue
        in_state[index] = current
        produced = set(current)
        for register in method.dest[index]:
            produced.add(register)
        if out_state[index] == produced:
            continue
        out_state[index] = produced
        for target in edges[index]:
            if 0 <= target < count and reachable[target]:
                pending.append(target)
        for handler in covering[index]:
            pending.append(handler)

    findings = []
    for index in range(count):
        if not reachable[index] or in_state[index] is None:
            continue
        defined = in_state[index]
        for register in method.reads[index]:
            if register in defined:
                continue
            findings.append((index, method.codes[index], register))
    return findings, method


def check_file(path):
    problems = []
    text = path.read_text(errors='replace')
    for match in METHOD_RE.finditer(text):
        block = match.group(0)
        header = block.splitlines()[0].strip()
        findings, _method = analyze(block)
        for index, code, register in findings:
            problems.append((path, index, header, code, register))
    return problems


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('root', type=Path, nargs='?',
                        default=Path('.tools/migrated-176'))
    parser.add_argument('--limit', type=int, default=50)
    args = parser.parse_args()

    problems = []
    files = sorted(args.root.rglob('*.smali'))
    for path in files:
        problems.extend(check_file(path))
    for path, index, header, code, register in problems[:args.limit]:
        print('%s  %s' % (path, header))
        print('    %r' % code)
        print('    register %s is not assigned on every path' % register)
    print('checked %d files, %d undefined register reads'
          % (len(files), len(problems)))
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
