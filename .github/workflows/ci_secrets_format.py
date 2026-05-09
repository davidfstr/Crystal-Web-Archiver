#!/usr/bin/env python3
"""
Interactively collects CI signing secrets and prints them in `KEY: value`
format to stdout, one per line.

Usage:
  .github/workflows/ci_secrets_format.py
  .github/workflows/ci_secrets_format.py | gh secret set --env distribution --env-file -
"""

import base64
import getpass
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile


# === Main ===

def main() -> None:
    _eprint('CI signing secrets')
    _eprint('==================')
    _eprint('Password-like prompts will not echo.')
    _eprint()

    apple_id = _prompt(
        '1Password item "Apple ID" → username',
        secret=False,
    )
    apple_team_id = _prompt(
        'https://developer.apple.com/account → Team ID (10 chars, e.g. AB12CD34EF)',
        secret=False,
    )
    apple_app_specific_password = _prompt(
        '1Password item "Apple ID - App Specific Password - GitHub Actions Notarization" → password',
        secret=True,
    )
    certificate_password = _prompt(
        '1Password item "Apple Developer ID Certificate (developerID_application.p12)" → password',
        secret=True,
    )

    certificate_p12_b64: str
    certificate_name: str | None
    if True:
        _eprint()
        _eprint('Path to developerID_application.zip or developerID_application.p12')
        _eprint('  (download from 1Password attachment)')
        certificate_filepath_str = _prompt('  Path', secret=False).strip()
        
        certificate_p12_bytes: bytes
        certificate_filepath = Path(certificate_filepath_str)
        if certificate_filepath.suffix == '.zip':
            with zipfile.ZipFile(certificate_filepath) as zf:
                p12_names = [n for n in zf.namelist() if n.endswith('.p12')]
                if not p12_names:
                    _eprint('Error: no .p12 file found in zip')
                    sys.exit(1)
                certificate_p12_bytes = zf.read(p12_names[0])
        else:
            certificate_p12_bytes = certificate_filepath.read_bytes()

        certificate_p12_b64 = base64.b64encode(certificate_p12_bytes).decode('ascii')

        detected_certificate_name = _try_extract_certificate_name(certificate_p12_bytes, certificate_password)
        if detected_certificate_name is not None:
            _eprint(f'  Detected certificate name: {detected_certificate_name!r}')
            answer = _prompt('  Use this for CERTIFICATE_NAME? [Y/n]', secret=False).strip().lower()
            certificate_name = detected_certificate_name if answer not in ('n', 'no') else None
        else:
            certificate_name = None
        if certificate_name is None:
            certificate_name = _prompt(
                'Certificate common name (e.g. "Developer ID Application: Your Name (TEAMID)")',
                secret=False,
            )

    _eprint()

    # Output alphabetically (matches GitHub's UI order)
    print(f'APPLE_APP_SPECIFIC_PASSWORD: {apple_app_specific_password}')
    print(f'APPLE_ID: {apple_id}')
    print(f'APPLE_TEAM_ID: {apple_team_id}')
    print(f'CERTIFICATE_NAME: {certificate_name}')
    print(f'CERTIFICATE_P12: {certificate_p12_b64}')
    print(f'CERTIFICATE_PASSWORD: {certificate_password}')


# === Utility ===

def _eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def _prompt(label: str, secret: bool = True) -> str:
    if secret:
        return getpass.getpass(f'{label}: ', stream=sys.stderr)
    else:
        print(f'{label}: ', end='', file=sys.stderr, flush=True)
        return input()


def _try_extract_certificate_name(p12_data: bytes, password: str) -> str | None:
    """Try to read the CN from a .p12 using openssl. Returns None on any failure."""
    pem_output: str
    with tempfile.NamedTemporaryFile(suffix='.p12') as f:
        f.write(p12_data)
        f.flush()

        try:
            result = subprocess.run(
                [
                    'openssl', 'pkcs12', '-in', f.name, '-nokeys',
                    '-passin', f'pass:{password}',
                    '-legacy',
                ],
                capture_output=True,
                text=True,
                check=True
            )
        except subprocess.CalledProcessError:
            return None
        else:
            pem_output = result.stdout

    x509_output: str
    try:
        result = subprocess.run(
            ['openssl', 'x509', '-noout', '-subject'],
            input=pem_output,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return None
    else:
        x509_output = result.stdout

    # NOTE: Handles both old (/CN=...) and new (CN = ...) OpenSSL subject formats
    m = re.search(r'CN\s*=\s*([^,/\n]+)', x509_output)
    return m.group(1).strip() if m else None


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
