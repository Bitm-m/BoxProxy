#!/usr/bin/env python3
"""Report reference type errors that the 171 -> 176 port introduces.

The dex verifier resolves every argument register against the parameter type
of the callee.  A port that re-anchors a hunk can leave a register holding a
different reference type than the callee expects: ``Object.getClass()`` hands
out a ``Class``, not the ``String`` the method declares.  Such a method fails
to verify at class load time even though every instruction shape and every
symbol reference is correct.

A standalone type checker over an obfuscated tree is noisy, because the
checker cannot see the whole class hierarchy.  The port, however, starts from
the pinned 176 upstream tree, so every type error that is *already* there is
known good.  The checker therefore runs over the upstream tree and over the
migrated tree and reports only the findings the port adds.
"""
import argparse
import re
from pathlib import Path

METHOD_RE = re.compile(r'^\.method.*?^\.end method', re.M | re.S)
CLASS_RE = re.compile(r'^\.class\s+.*?(L[A-Za-z0-9_/$-]+;)', re.M)
SUPER_RE = re.compile(r'^\.super\s+(L[A-Za-z0-9_/$-]+;)', re.M)
IMPLEMENTS_RE = re.compile(r'^\.implements\s+(L[A-Za-z0-9_/$-]+;)', re.M)
INVOKE_RE = re.compile(
    r'^\s*invoke-\S+\s*(?:/range\s*)?\{([^}]*)\}\s*,\s*'
    r'(L[A-Za-z0-9_/$-]+;)->([^\s(:]+)(\([^)]*\))(\S+)')
MOVE_RESULT_RE = re.compile(r'^\s*move-result-object\s+([vp]\d+)\s*$')
NEW_INSTANCE_RE = re.compile(r'^\s*new-instance\s+([vp]\d+),\s*(L[A-Za-z0-9_/$-]+;)\s*$')
CONST_STRING_RE = re.compile(r'^\s*const-string(?:/jumbo)?\s+([vp]\d+)\s*,')
SGET_OBJECT_RE = re.compile(
    r'^\s*sget-object\s+([vp]\d+),\s*(L[A-Za-z0-9_/$-]+;)->([^\s:]+):(L[A-Za-z0-9_/$-]+;)\s*$')
IGET_OBJECT_RE = re.compile(
    r'^\s*iget-object\s+([vp]\d+),\s*(?:[vp]\d+,\s*)?'
    r'(L[A-Za-z0-9_/$-]+;)->([^\s:]+):(L[A-Za-z0-9_/$-]+;)\s*$')
MOVE_OBJECT_RE = re.compile(r'^\s*move-object(?:/from16)?\s+([vp]\d+),\s*([vp]\d+)\s*$')
CHECK_CAST_RE = re.compile(
    r'^\s*check-cast\s+([vp]\d+),\s*(L[A-Za-z0-9_/$-]+;)\s*$')
NOISE_RE = re.compile(r'^\s*(\.line\b|\.local\b|\.end local\b|\.restart local\b|'
                       r'\.param\b|\.end param\b|\.prologue\b|\.source\b|\.registers\b|'
                       r'\.locals\b)')
LABEL_RE = re.compile(r'^\s*:\w+')

JDK_SUPERS = {
    'Ljava/lang/Integer;': 'Ljava/lang/Number;',
    'Ljava/lang/Long;': 'Ljava/lang/Number;',
    'Ljava/lang/Short;': 'Ljava/lang/Number;',
    'Ljava/lang/Byte;': 'Ljava/lang/Number;',
    'Ljava/lang/Double;': 'Ljava/lang/Number;',
    'Ljava/lang/Float;': 'Ljava/lang/Number;',
    'Ljava/lang/Number;': 'Ljava/lang/Object;',
    'Ljava/lang/Boolean;': 'Ljava/lang/Object;',
    'Ljava/lang/Character;': 'Ljava/lang/Object;',
    'Ljava/lang/Class;': 'Ljava/lang/Object;',
    'Ljava/lang/String;': 'Ljava/lang/Object;',
    'Ljava/lang/StringBuilder;': 'Ljava/lang/Object;',
    'Ljava/lang/Exception;': 'Ljava/lang/Throwable;',
    'Ljava/lang/RuntimeException;': 'Ljava/lang/Exception;',
    'Ljava/lang/Error;': 'Ljava/lang/Throwable;',
    'Ljava/lang/Throwable;': 'Ljava/lang/Object;',
    'Ljava/io/IOException;': 'Ljava/lang/Exception;',
    'Ljava/io/FileNotFoundException;': 'Ljava/io/IOException;',
}


def descriptor_types(descriptor):
    inner = descriptor[descriptor.index('(') + 1:descriptor.rindex(')')]
    params, index = [], 0
    while index < len(inner):
        char = inner[index]
        while char == '[':
            index += 1
            char = inner[index]
        if char == 'L':
            end = inner.find(';', index)
            params.append(inner[index:end + 1])
            index = end + 1
        elif char in 'JD':
            params.append(char)
            index += 1
        else:
            params.append(char)
            index += 1
    returns = descriptor[descriptor.rindex(')') + 1:]
    return params, returns


JDK_INTERFACES = {
    'Ljava/lang/CharSequence;', 'Ljava/lang/Comparable;', 'Ljava/lang/Runnable;',
    'Ljava/lang/Iterable;', 'Ljava/lang/Cloneable;', 'Ljava/io/Serializable;',
    'Ljava/io/Closeable;', 'Ljava/io/Flushable;', 'Ljava/io/Readable;',
    'Ljava/util/Collection;', 'Ljava/util/List;', 'Ljava/util/Set;',
    'Ljava/util/Map;', 'Ljava/util/Queue;', 'Ljava/util/Deque;',
    'Ljava/util/Iterator;', 'Ljava/util/ListIterator;', 'Ljava/util/Comparator;',
    'Ljava/util/function/Function;', 'Ljava/util/function/Supplier;',
    'Ljava/util/function/Consumer;', 'Ljava/util/function/Predicate;',
    'Ljava/util/concurrent/Callable;', 'Ljava/util/concurrent/Future;',
    'Ljava/util/concurrent/Executor;', 'Ljava/lang/reflect/Type;',
    'Ljava/lang/reflect/GenericDeclaration;', 'Ljava/lang/reflect/AnnotatedElement;',
    'Ljava/lang/annotation/Annotation;', 'Ljava/lang/Iterable;',
    'Landroid/content/Context;', 'Landroid/view/View;',
}


def collect_hierarchy(root):
    supers, interfaces = {}, set(JDK_INTERFACES)
    for path in root.rglob('*.smali'):
        text = path.read_text(errors='replace')
        match = CLASS_RE.search(text)
        if not match:
            continue
        owner = match.group(1)
        parent = SUPER_RE.search(text)
        supers[owner] = parent.group(1) if parent else 'Ljava/lang/Object;'
        for implemented in IMPLEMENTS_RE.findall(text):
            interfaces.add(implemented)
    for owner, parent in JDK_SUPERS.items():
        supers.setdefault(owner, parent)
    return supers, interfaces


def assignable(source, target, supers, interfaces):
    if source == target:
        return True
    if target == 'Ljava/lang/Object;':
        return True
    if target in interfaces:
        return True
    current = supers.get(source)
    while current:
        if current == target:
            return True
        current = supers.get(current)
    return False


def parameter_types(header):
    inner = header[header.index('(') + 1:header.rindex(')')]
    params, index = [], 0
    while index < len(inner):
        char = inner[index]
        while char == '[':
            index += 1
            char = inner[index]
        if char == 'L':
            end = inner.find(';', index)
            params.append(inner[index:end + 1])
            index = end + 1
        elif char in 'JD':
            params.append(char)
            index += 1
        else:
            params.append(char)
            index += 1
    return params


def check_method(lines, supers, interfaces):
    problems = []
    types = {}
    header = lines[0]
    params = parameter_types(header)
    offset = 0 if ' static ' in header + ' ' else 1
    for position, declared in enumerate(params):
        if declared.startswith('L'):
            types['p' + str(position + offset)] = declared

    significant = []
    for number, raw in enumerate(lines, 1):
        code = raw.strip()
        if not code or NOISE_RE.match(code) or LABEL_RE.match(code):
            continue
        significant.append((number, code))

    for position, (number, code) in enumerate(significant):
        following = significant[position + 1][1] if position + 1 < len(significant) else None
        match = INVOKE_RE.match(code)
        if match:
            registers = [item.strip() for item in match.group(1).split(',')]
            declared_params, returns = descriptor_types(match.group(4) + match.group(5))
            if len(registers) == len(declared_params):
                for register, declared in zip(registers, declared_params):
                    if not declared.startswith('L'):
                        continue
                    known = types.get(register)
                    if known is None or known == 'Ljava/lang/Object;':
                        continue
                    if not assignable(known, declared, supers, interfaces):
                        problems.append((number, code, register, known, declared))
            if returns.startswith('L') and following and following.startswith('move-result-object'):
                types['__pending__'] = returns
            continue
        match = MOVE_RESULT_RE.match(code)
        if match:
            pending = types.pop('__pending__', None)
            if pending:
                types[match.group(1)] = pending
            else:
                types.pop(match.group(1), None)
            continue
        types.pop('__pending__', None)
        match = NEW_INSTANCE_RE.match(code)
        if match:
            types[match.group(1)] = match.group(2)
            continue
        match = CONST_STRING_RE.match(code)
        if match:
            types[match.group(1)] = 'Ljava/lang/String;'
            continue
        match = SGET_OBJECT_RE.match(code) or IGET_OBJECT_RE.match(code)
        if match:
            types[match.group(1)] = match.group(4)
            continue
        match = MOVE_OBJECT_RE.match(code)
        if match:
            source = types.get(match.group(2))
            if source:
                types[match.group(1)] = source
            else:
                types.pop(match.group(1), None)
            continue
        match = CHECK_CAST_RE.match(code)
        if match:
            types[match.group(1)] = match.group(2)
            continue
    return problems


def scan(root, supers, interfaces):
    methods, findings = set(), {}
    for path in sorted(root.rglob('*.smali')):
        text = path.read_text(errors='replace')
        relative = str(path.relative_to(root))
        for match in METHOD_RE.finditer(text):
            block = match.group(0).splitlines()
            header = block[0].strip()
            methods.add((relative, header))
            problems = check_method(block, supers, interfaces)
            if problems:
                findings[(relative, header)] = problems
    return methods, findings


def signature(problem):
    _, code, register, known, declared = problem
    call = code.split('},')[-1].strip()
    # The owner type may legitimately change (a Toast hunk rewrites the
    # callee), so only the member name and the descriptor are compared.
    if '->' in call:
        call = call.split('->', 1)[1]
    return (register, known, declared, call)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path, nargs='?',
                        default=Path('.tools/migrated-176'))
    parser.add_argument('--baseline', type=Path, default=Path('.tools/upstream-173/decompiled'),
                        help='tree the port started from; its findings are known good')
    parser.add_argument('--limit', type=int, default=40)
    args = parser.parse_args()
    supers, interfaces = collect_hierarchy(args.root)
    base_supers, base_interfaces = collect_hierarchy(args.baseline)
    for owner, parent in base_supers.items():
        supers.setdefault(owner, parent)
    interfaces |= base_interfaces
    baseline_methods, baseline = scan(args.baseline, base_supers, base_interfaces)
    _, findings = scan(args.root, supers, interfaces)
    added = []
    for key, problems in findings.items():
        if key not in baseline_methods:
            continue
        known = {signature(problem) for problem in baseline.get(key, [])}
        for problem in problems:
            if signature(problem) not in known:
                added.append((key, problem))
    for key, problem in added[:args.limit]:
        relative, header = key
        number, code, register, held, declared = problem
        print('%s:%d  %s' % (relative, number, header))
        print('    %s' % code)
        print('    %s holds %s but the callee wants %s' % (register, held, declared))
    print('baseline %d methods, %d with findings; %d type errors introduced by the port'
          % (len(baseline_methods), len(baseline), len(added)))
    return 1 if added else 0


if __name__ == '__main__':
    raise SystemExit(main())
