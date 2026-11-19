#!/usr/bin/env python3
"""Reproduce the reviewed 171 -> 194 full-custom migration in a NEW directory.

The 194 candidate is not a straight patch of the pinned 194 upstream tree: the
customized 171 build carries 51 reviewed method customizations, 1353 runtime
helper additions and 15 manifest changes that have to be relocated onto the
194 upstream tree through the reviewed 171 -> 194 class map.

The pipeline is fully deterministic and derives every input from artifacts that
are committed to this repository:

    upstream/26.11.16.25abc84   pinned 171 upstream snapshot
      -> migrate_upstream.py    the customized 171 tree (hash-pinned plan)
    upstream/26.11.19.bf82603   pinned 194 upstream snapshot
      -> upstream_snapshot.py   the immutable 194 upstream tree
    migration/class-map.json    the reviewed class map (8012 classes)
      -> build_173_maps.py      the reviewed type/member/field map
      -> port_194_candidate.py  the customized 194 candidate tree

Nothing outside --output is modified, and the output directory is published
atomically: a failed step leaves no half-migrated tree for a build to pick up.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]

SNAPSHOT_171 = 'upstream/26.11.16.25abc84'
SNAPSHOT_194 = 'upstream/26.11.19.bf82603'
VERSION_NAME = '26.11.19.bf82603'
VERSION_CODE = '194'


def run(command):
    print('>> ' + ' '.join(str(part) for part in command), flush=True)
    subprocess.run([str(part) for part in command], check=True, cwd=REPO)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', type=Path, required=True,
                        help='directory that receives the customized 194 tree')
    parser.add_argument('--keep-scratch', action='store_true',
                        help='keep the intermediate scratch trees for inspection')
    args = parser.parse_args()

    output = (REPO / args.output).resolve() if not args.output.is_absolute() else args.output.resolve()
    runtime = (REPO / 'decompiled').resolve()
    if output == runtime or runtime in output.parents or output in runtime.parents:
        raise SystemExit('refusing to publish over the customized runtime project')
    if (output / 'decompiled').resolve() == runtime:
        raise SystemExit('refusing to publish over the customized runtime project')
    if output.exists():
        raise SystemExit('refusing to overwrite an existing output directory: ' + str(output))

    scratch_parent = output.parent
    scratch_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.boxproxy-migrate-194-',
                                     dir=scratch_parent) as scratch:
        scratch = Path(scratch)
        up171 = scratch / 'upstream-171'
        custom171 = scratch / 'customized-171'
        up194 = scratch / 'upstream-194'
        maps = scratch / 'resolved-maps-194.json'
        candidate = scratch / 'candidate'

        run([sys.executable, 'scripts/upstream_snapshot.py', SNAPSHOT_171,
             '--extract', up171])
        run([sys.executable, 'scripts/migrate_upstream.py',
             '--snapshot', SNAPSHOT_171, '--output', custom171])
        run([sys.executable, 'scripts/upstream_snapshot.py', SNAPSHOT_194,
             '--extract', up194])
        run([sys.executable, 'scripts/build_173_maps.py',
             '--old', up171 / 'decompiled',
             '--new', up194 / 'decompiled',
             '--class-map', Path(SNAPSHOT_194) / 'migration' / 'class-map.json',
             '--coverage', Path(SNAPSHOT_194) / 'migration' / 'coverage.json',
             '--review', Path(SNAPSHOT_194) / 'migration' / 'class-map-overrides.json',
             '--output', maps])
        run([sys.executable, 'scripts/port_194_candidate.py',
             '--old', up171 / 'decompiled',
             '--new', up194 / 'decompiled',
             '--custom', custom171 / 'decompiled',
             '--coverage', Path(SNAPSHOT_194) / 'migration' / 'coverage.json',
             '--maps', maps,
             '--report-dir', scratch / 'report',
             '--output', candidate])

        project = candidate
        if not (project / 'apktool.yml').is_file():
            raise SystemExit('the port did not produce an Apktool project')
        config = (project / 'apktool.yml').read_text().splitlines()
        if ('  versionCode: ' + str(VERSION_CODE)) not in config:
            raise SystemExit('migrated project carries an unexpected versionCode')
        if ('  versionName: ' + VERSION_NAME) not in config:
            raise SystemExit('migrated project carries an unexpected versionName')

        report = json.loads((scratch / 'report' / 'delta-stage6-report.json').read_text())
        if report.get('ok') != 51 or report.get('errors'):
            raise SystemExit('the port report is not clean: ' + json.dumps(report)[:400])

        run([sys.executable, 'scripts/verify_194_custom_hunks.py',
             '--old', up171 / 'decompiled',
             '--new', up194 / 'decompiled',
             '--custom', custom171 / 'decompiled',
             '--coverage', Path(SNAPSHOT_194) / 'migration' / 'coverage.json',
             '--maps', maps,
             '--output', project])

        # ART rejects a class whose verifier finds a register that is read on
        # a path where it was never written; the shape comparison above is
        # order-insensitive and cannot see that, so run the control flow
        # analysis before the tree is published.
        run([sys.executable, 'scripts/check_smali_register_flow.py', project])
        run([sys.executable, 'scripts/check_smali_return_types.py', project])

        shutil.copytree(project, output / 'decompiled')
        if args.keep_scratch:
            keep = output.with_name(output.name + '-scratch')
            shutil.copytree(scratch, keep)
            print('Scratch trees kept at ' + str(keep))

    print('Prepared 194 migration candidate: ' + str(output / 'decompiled'))


if __name__ == '__main__':
    main()
