#!/usr/bin/env python3
"""Page-align the uncompressed entries of an APK.

The Android build-tools ``zipalign`` binary is not available in every build
environment, but the box proxy APK ships uncompressed shared libraries and
declares ``android:extractNativeLibs="false"``, so the library payloads have to
start on a 4096 byte page boundary or the installer rejects the package.

This tool reproduces the part of ``zipalign`` the release build needs:

* ``lib/**.so`` entries are aligned to 4096 bytes,
* every other uncompressed entry (notably ``resources.arsc``) is aligned to
  4 bytes,
* compressed entries are copied verbatim, exactly like the upstream tool.

The padding is stored in the extra field using the Android alignment extra
field id ``0xd935``.  The compressed payload bytes and the data descriptors are
copied unchanged, so the archive stays byte identical apart from the padding.
"""
import argparse
import struct
import sys
import zipfile

LOCAL_HEADER = 0x04034B50
CENTRAL_HEADER = 0x02014B50
END_OF_CENTRAL = 0x06054B50
DATA_DESCRIPTOR = 0x08074B50
ALIGNMENT_EXTRA_ID = 0xD935
PAGE_ALIGNMENT = 4096
FILE_ALIGNMENT = 4
DATA_DESCRIPTOR_FLAG = 0x08


def alignment_for(name, page_align):
    if page_align and name.endswith('.so'):
        return PAGE_ALIGNMENT
    return FILE_ALIGNMENT


def read_archive(path):
    """Return the entries with their raw payload and the central directory."""
    archive = zipfile.ZipFile(path)
    entries = []
    with open(path, 'rb') as handle:
        for info in archive.infolist():
            handle.seek(info.header_offset)
            header = handle.read(30)
            if len(header) != 30 or struct.unpack('<I', header[:4])[0] != LOCAL_HEADER:
                raise SystemExit('bad local header for ' + info.filename)
            (version, flags, method, mtime, mdate, crc, csize, usize,
             name_len, extra_len) = struct.unpack('<HHHHHIIIHH', header[4:30])
            name = handle.read(name_len)
            extra = handle.read(extra_len)
            # The central directory holds the authoritative sizes, the local
            # header leaves them empty when a data descriptor is used.
            payload = handle.read(info.compress_size)
            if len(payload) != info.compress_size:
                raise SystemExit('truncated payload for ' + info.filename)
            descriptor = b''
            if flags & DATA_DESCRIPTOR_FLAG:
                descriptor = handle.read(4)
                if struct.unpack('<I', descriptor)[0] == DATA_DESCRIPTOR:
                    descriptor += handle.read(12)
                else:
                    descriptor += handle.read(8)
            entries.append({
                'info': info,
                'name': name,
                'extra': extra,
                'payload': payload,
                'descriptor': descriptor,
                'version': version,
                'flags': flags,
                'method': method,
                'mtime': mtime,
                'mdate': mdate,
                'crc': crc,
                'csize': csize,
                'usize': usize,
            })
    return archive, entries


def aligned_extra(entry, offset, alignment):
    """Return the extra field that puts the payload on an aligned offset.

    The same extra field is written to the local and to the central header so
    that both stay in sync, which is what the upstream tool does as well.
    """
    if entry['info'].compress_type != zipfile.ZIP_STORED or alignment <= 1:
        return entry['extra']
    base = offset + 30 + len(entry['name']) + len(entry['extra'])
    record = (-base) % alignment
    if record == 0:
        return entry['extra']
    if record < 4:
        record += alignment
    padding = record - 4
    return (entry['extra'] + struct.pack('<HH', ALIGNMENT_EXTRA_ID, padding)
            + b'\x00' * padding)


def align(source, destination, page_align=True):
    archive, entries = read_archive(source)
    with open(destination, 'wb') as out:
        offsets, extras = [], []
        for entry in entries:
            offset = out.tell()
            offsets.append(offset)
            alignment = alignment_for(entry['info'].filename, page_align)
            extra = aligned_extra(entry, offset, alignment)
            extras.append(extra)
            out.write(struct.pack('<IHHHHHIIIHH', LOCAL_HEADER, entry['version'],
                                 entry['flags'], entry['method'], entry['mtime'],
                                 entry['mdate'], entry['crc'], entry['csize'],
                                 entry['usize'], len(entry['name']), len(extra)))
            out.write(entry['name'])
            out.write(extra)
            out.write(entry['payload'])
            out.write(entry['descriptor'])
        central_offset = out.tell()
        for entry, offset, extra in zip(entries, offsets, extras):
            info = entry['info']
            # Rebuild the central record from the archive metadata.
            out.write(struct.pack('<IHHHHHHIIIHHHHHII', CENTRAL_HEADER,
                                 (info.create_system << 8) | info.create_version,
                                 entry['version'], entry['flags'], entry['method'],
                                 entry['mtime'], entry['mdate'], info.CRC,
                                 info.compress_size, info.file_size,
                                 len(entry['name']), len(extra),
                                 len(info.comment or b''), 0, info.internal_attr,
                                 info.external_attr, offset))
            out.write(entry['name'])
            out.write(extra)
            out.write(info.comment or b'')
        central_size = out.tell() - central_offset
        out.write(struct.pack('<IHHHHIIH', END_OF_CENTRAL, 0, 0,
                              len(entries), len(entries), central_size,
                              central_offset, 0))
        comment = archive.comment or b''
        if comment:
            out.write(comment)
    return len(entries)


def verify(path, page_align=True):
    """Report every uncompressed entry whose payload is not aligned."""
    archive, entries = read_archive(path)
    problems = []
    for entry in entries:
        info = entry['info']
        alignment = alignment_for(info.filename, page_align)
        if info.compress_type != zipfile.ZIP_STORED:
            continue
        offset = info.header_offset + 30 + len(entry['name']) + len(entry['extra'])
        if offset % alignment:
            problems.append((info.filename, offset, alignment))
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-c', '--check', action='store_true',
                        help='only verify the alignment of an archive')
    parser.add_argument('-p', '--page-align-libs', dest='page_align',
                        action='store_true', default=True,
                        help='page align shared libraries (default)')
    parser.add_argument('--no-page-align-libs', dest='page_align',
                        action='store_false',
                        help='do not page align shared libraries')
    parser.add_argument('source')
    parser.add_argument('destination', nargs='?')
    args = parser.parse_args()
    if args.check:
        problems = verify(args.source, args.page_align)
        for name, offset, alignment in problems:
            print('misaligned: %s (offset %d, alignment %d)' % (name, offset, alignment))
        if problems:
            return 1
        print('Verification successful')
        return 0
    if not args.destination:
        raise SystemExit('a destination archive is required')
    count = align(args.source, args.destination, args.page_align)
    print('aligned %d entries into %s' % (count, args.destination))
    return 0


if __name__ == '__main__':
    sys.exit(main())
