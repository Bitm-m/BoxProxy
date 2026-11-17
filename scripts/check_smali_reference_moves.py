#!/usr/bin/env python3
"""Reject potentially verifier-unsafe no-op object moves in a Smali project.

A move-object from a register to the same physical register is redundant, but
ART still verifies the source as a reference. In methods with ``.locals``, a
parameter register such as p0 can alias a v-register that was just reused for
an integer. Resolve p/v aliases so this risky pattern cannot slip through.
"""
import argparse
import re
from pathlib import Path

METHOD_RE = re.compile(r"^\.method[^\n]*$.*?^\.end method[ \t]*$", re.M | re.S)
REGISTER_DIRECTIVE_RE = re.compile(
    r"^\s*\.(locals|registers)\s+(\d+)\s*(?:#.*)?$"
)
OBJECT_MOVE_RE = re.compile(
    r"^\s*move-object(?:/(?:from16|16))?\s+([vp]\d+)\s*,\s*([vp]\d+)\s*$"
)


def method_signature(block):
    return block.splitlines()[0].split()[-1]


def parameter_words(signature):
    start = signature.find('(')
    end = signature.find(')', start + 1)
    if start < 0 or end < 0:
        raise ValueError('invalid method descriptor: ' + signature)
    descriptor = signature[start + 1:end]
    words = 0
    index = 0
    while index < len(descriptor):
        char = descriptor[index]
        if char == '[':
            while index < len(descriptor) and descriptor[index] == '[':
                index += 1
            if index >= len(descriptor):
                raise ValueError('invalid array parameter in ' + signature)
            if descriptor[index] == 'L':
                terminator = descriptor.find(';', index)
                if terminator < 0:
                    raise ValueError('invalid object parameter in ' + signature)
                index = terminator + 1
            else:
                index += 1
            words += 1
        elif char == 'L':
            terminator = descriptor.find(';', index)
            if terminator < 0:
                raise ValueError('invalid object parameter in ' + signature)
            index = terminator + 1
            words += 1
        elif char in 'JD':
            index += 1
            words += 2
        else:
            index += 1
            words += 1
    return words


def physical_register(register, parameter_base, parameter_count, total_registers):
    kind, number_text = register[0], register[1:]
    number = int(number_text)
    if kind == 'p':
        if number >= parameter_count:
            raise ValueError(f'parameter register {register} is outside the {parameter_count}-word input window')
        number += parameter_base
    if number >= total_registers:
        raise ValueError(f'register {register} resolves outside the {total_registers}-register frame')
    return number


def scan_text(text, path='<memory>'):
    errors = []
    for block in METHOD_RE.finditer(text):
        method = block.group(0)
        header = method.splitlines()[0]
        signature = method_signature(method)
        directives = []
        for number, line in enumerate(method.splitlines(), 1):
            match = REGISTER_DIRECTIVE_RE.match(line)
            if match:
                directives.append((number, match.group(1), int(match.group(2))))
        moves = []
        for number, line in enumerate(method.splitlines(), 1):
            instruction = line.split('#', 1)[0]
            match = OBJECT_MOVE_RE.match(instruction)
            if match:
                moves.append((number, match.group(1), match.group(2), line.strip()))
        if not moves:
            continue
        if len(directives) != 1:
            errors.append(
                f'{path}:{signature}: expected one .locals/.registers directive, found {len(directives)}'
            )
            continue
        directive_line, directive_kind, count = directives[0]
        try:
            parameter_count = parameter_words(signature)
            if not re.search(r'(?:^|\s)static(?:\s|$)', header.split('(', 1)[0]):
                parameter_count += 1
            if directive_kind == 'locals':
                parameter_base = count
                total_registers = count + parameter_count
            else:
                total_registers = count
                parameter_base = total_registers - parameter_count
                if parameter_base < 0:
                    raise ValueError('input words exceed the .registers frame size')
            for number, destination, source, instruction in moves:
                dest_index = physical_register(
                    destination, parameter_base, parameter_count, total_registers)
                source_index = physical_register(
                    source, parameter_base, parameter_count, total_registers)
                if dest_index == source_index:
                    physical_name = f'v{dest_index}'
                    errors.append(
                        f'{path}:{number}: {signature}: {instruction} aliases '
                        f'{physical_name}; move-object self-copies may fail verification after register reuse'
                    )
        except ValueError as error:
            errors.append(f'{path}:{directive_line}: {signature}: {error}')
    return errors


def scan_project(root, replacements=None):
    root = Path(root)
    replacements = replacements or {}
    files = sorted(root.rglob('*.smali'))
    errors = []
    for path in files:
        text = replacements.get(path)
        if text is None:
            text = path.read_text(errors='replace')
        errors.extend(scan_text(text, str(path)))
    return len(files), errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path, help='decoded project or Smali directory tree')
    args = parser.parse_args()
    count, errors = scan_project(args.project)
    for error in errors:
        print(error)
    if errors:
        raise SystemExit(f'Found {len(errors)} verifier-unsafe object self-move(s) in {count} Smali files.')
    print(f'Checked {count} Smali files: no register-aliasing move-object instructions.')


if __name__ == '__main__':
    main()
