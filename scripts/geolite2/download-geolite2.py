#!/usr/bin/env python3
"""Download the MaxMind GeoLite2-City database for the identity service.

The GeoLite2 DB enables approximate login-location lookups (city/state/country)
for the "New Login Detected" security-alert email. Without it the alert email
degrades gracefully to masked-IP-only.

Usage:
    python scripts/geolite2/download-geolite2.py --license-key $MAXMIND_LICENSE_KEY
    python scripts/geolite2/download-geolite2.py            # uses GEOIP_LICENSE_KEY env

Output (default): .local/geolite2/GeoLite2-City.mmdb  (gitignored)

Point the identity service at it with:
    IDENTITY_GEOIP_DB_PATH=.local/geolite2/GeoLite2-City.mmdb
"""

from __future__ import annotations

import argparse
import os
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

EDITION = "GeoLite2-City"
DOWNLOAD_URL = (
    "https://download.maxmind.com/app/geoip_download"
    "?edition_id={edition}&license_key={key}&suffix=tar.gz"
)
DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / ".local" / "geolite2" / f"{EDITION}.mmdb"


def _env_or_license_key(license_key: str | None) -> str:
    key = license_key or os.environ.get("GEOIP_LICENSE_KEY", "")
    if not key:
        raise SystemExit(
            "Missing MaxMind license key. Pass --license-key or set GEOIP_LICENSE_KEY.\n"
            "Get a free license key at https://www.maxmind.com/en/geolite2/signup"
        )
    return key


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--license-key", default=None, help="MaxMind GeoLite2 license key")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"output .mmdb path (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    key = _env_or_license_key(args.license_key)
    output: Path = args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    url = DOWNLOAD_URL.format(edition=EDITION, key=key)
    print(f"Downloading {EDITION} from MaxMind...")

    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tmp_name = tmp.name
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                while chunk := response.read(1 << 16):
                    tmp.write(chunk)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                print(f"MaxMind rejected the license key (HTTP {exc.code}).", file=sys.stderr)
            else:
                print(f"Download failed: {exc}", file=sys.stderr)
            os.unlink(tmp_name)
            return 1
        except (OSError, urllib.error.URLError) as exc:
            print(f"Download failed: {exc}", file=sys.stderr)
            os.unlink(tmp_name)
            return 1

    try:
        with tarfile.open(tmp_name, "r:gz") as archive:
            member = next(m for m in archive.getmembers() if m.name.endswith(f"{EDITION}.mmdb"))
            src = archive.extractfile(member)
            if src is None:
                raise RuntimeError(f"{EDITION}.mmdb missing from archive")
            with open(output, "wb") as dest:
                dest.write(src.read())
    except Exception as exc:  # surface any archive error to the user
        print(f"Extraction failed: {exc}", file=sys.stderr)
        os.unlink(tmp_name)
        return 1
    finally:
        os.unlink(tmp_name)

    print(f"Saved {EDITION} to {output}")
    print(f"Set IDENTITY_GEOIP_DB_PATH={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
