#!/usr/bin/env python3
"""Offline structural checks for the Xiaomi Camera Native HACS repository."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = 'xiaomi_camera_native'
REQUIRED_FIELDS = {'domain', 'documentation', 'issue_tracker', 'codeowners', 'name', 'version'}


def inspect_repository(root: Path = ROOT) -> list[str]:
    errors: list[str] = []

    def required(rel: str) -> Path:
        path = root / rel
        if not path.is_file():
            errors.append(f'Missing required file: {rel}')
        return path

    component = root / 'custom_components' / DOMAIN
    manifest_path = required(f'custom_components/{DOMAIN}/manifest.json')
    hacs_path = required('hacs.json')
    required('README.md')
    required(f'custom_components/{DOMAIN}/__init__.py')
    required(f'custom_components/{DOMAIN}/brand/icon.png')
    required('.github/workflows/validate.yml')
    required('VALIDATION.md')
    required('HACS_PUBLISHING.md')

    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            missing = REQUIRED_FIELDS - set(manifest)
            if missing:
                errors.append(f'Manifest missing: {", ".join(sorted(missing))}')
            if manifest.get('domain') != DOMAIN:
                errors.append('Domain does not match component folder name')
            if manifest.get('version') != '0.3.14':
                errors.append('Manifest version must be 0.3.14 for this upgrade')
            if not manifest.get('codeowners'):
                errors.append('Manifest needs at least one codeowner')
            expected_order = ['domain', 'name'] + sorted(
                key for key in manifest if key not in ('domain', 'name')
            )
            if list(manifest) != expected_order:
                errors.append(
                    'Manifest keys must be ordered domain, name, then alphabetically'
                )
        except (ValueError, UnicodeDecodeError) as exc:
            errors.append(f'Invalid manifest JSON: {exc}')

    if hacs_path.is_file():
        try:
            hacs = json.loads(hacs_path.read_text(encoding='utf-8'))
            if hacs.get('name') != 'Xiaomi Camera Native':
                errors.append('Unexpected HACS display name')
        except (ValueError, UnicodeDecodeError) as exc:
            errors.append(f'Invalid hacs.json: {exc}')

    if component.is_dir():
        comps = sorted(p.name for p in component.parent.iterdir() if p.is_dir())
        if comps != [DOMAIN]:
            errors.append('HACS integration repo must contain only one component: ' + str(comps))

    return errors


if __name__ == '__main__':
    failures = inspect_repository()
    for failure in failures:
        print('FAIL:', failure, file=sys.stderr)
    if failures:
        raise SystemExit(1)
    print('PASS: Xiaomi Camera Native offline packaging checks')
