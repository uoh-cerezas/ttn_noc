#!/usr/bin/env python3
"""Synchronize TTN end-device user locations from a CSV file.

The command is intentionally read-only unless both ``--apply`` and ``--yes``
are supplied. It preserves any other TTN location sources by merging the
spreadsheet coordinates into the existing ``locations.user`` entry.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from typing import Any

try:
    import requests
except ImportError:  # Keep --help and CSV validation usable before installation.
    requests = None  # type: ignore[assignment]


@dataclass(frozen=True)
class LocationRow:
    application_id: str
    device_id: str
    latitude: float
    longitude: float
    altitude: float | None


def read_rows(path: str) -> list[LocationRow]:
    rows: list[LocationRow] = []
    seen: set[tuple[str, str]] = set()
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"application_id", "device_id", "latitude", "longitude", "altitude"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV missing columns: {', '.join(sorted(missing))}")
        for line_number, raw in enumerate(reader, start=2):
            app = (raw.get("application_id") or "").strip()
            device = (raw.get("device_id") or "").strip()
            if not app and not device:
                continue
            if not app or not device:
                raise ValueError(f"Line {line_number}: application_id and device_id are required")
            key = (app, device)
            if key in seen:
                raise ValueError(f"Line {line_number}: duplicate device {app}/{device}")
            seen.add(key)
            try:
                latitude = float(raw["latitude"])
                longitude = float(raw["longitude"])
                altitude_text = (raw.get("altitude") or "").strip()
                altitude = float(altitude_text) if altitude_text else None
            except (TypeError, ValueError) as error:
                raise ValueError(f"Line {line_number}: invalid coordinate: {error}") from error
            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise ValueError(f"Line {line_number}: coordinate outside valid range")
            rows.append(LocationRow(app, device, latitude, longitude, altitude))
    return rows


def number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def location_from_row(row: LocationRow) -> dict[str, float | int]:
    location: dict[str, float | int] = {
        "latitude": row.latitude,
        "longitude": row.longitude,
    }
    if row.altitude is not None:
        # TTN's Location.altitude is int32; the spreadsheet terrain altitude
        # may contain decimals, so use the nearest meter.
        location["altitude"] = int(round(row.altitude))
    return location


def same_location(current: dict[str, Any], desired: dict[str, float]) -> bool:
    for key, expected in desired.items():
        actual = number(current.get(key))
        if actual is None or abs(actual - expected) > 1e-7:
            return False
    return True


def api_client() -> tuple[requests.Session, str]:
    if requests is None:
        raise RuntimeError("Install dependencies first: python3 -m pip install -r requirements.txt")
    token = os.getenv("TTN_API_KEY", "").strip()
    if not token:
        raise RuntimeError("TTN_API_KEY is not configured")
    region = os.getenv("TTN_IDENTITY_REGION", "eu1").strip() or "eu1"
    base = os.getenv(
        "TTN_IDENTITY_BASE_URL",
        f"https://{region}.cloud.thethings.network",
    ).rstrip("/")
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})
    return session, base


def get_device(session: requests.Session, base: str, row: LocationRow, timeout: float) -> dict[str, Any]:
    url = f"{base}/api/v3/applications/{row.application_id}/devices/{row.device_id}"
    response = session.get(
        url,
        params={"field_mask": "ids,name,locations"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def update_device(
    session: requests.Session,
    base: str,
    row: LocationRow,
    locations: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    url = f"{base}/api/v3/applications/{row.application_id}/devices/{row.device_id}"
    payload = {
        "end_device": {
            "ids": {
                "application_ids": {"application_id": row.application_id},
                "device_id": row.device_id,
            },
            "locations": locations,
        },
        "field_mask": {"paths": ["locations"]},
    }
    response = session.put(
        url,
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv",
        default="config/sensor_locations.csv",
        help="CSV generated from the sensor spreadsheet",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply differences to TTN (requires --yes)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm TTN updates when used together with --apply",
    )
    parser.add_argument(
        "--only",
        action="append",
        metavar="APPLICATION_ID/DEVICE_ID",
        help="Limit the run to one or more explicitly named devices",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    if args.yes and not args.apply:
        parser.error("--yes is only valid together with --apply")
    if args.apply and not args.yes:
        parser.error("Refusing to update TTN without both --apply and --yes")

    try:
        rows = read_rows(args.csv)
        session, base = api_client()
    except (OSError, ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    if args.only:
        selected = set(args.only)
        rows = [row for row in rows if f"{row.application_id}/{row.device_id}" in selected]
        if not rows:
            print("ERROR: --only did not match any CSV row", file=sys.stderr)
            return 2

    print(f"Source: {args.csv}")
    print(f"TTN endpoint: {base}")
    print(f"Devices: {len(rows)}")
    print("Mode: APPLY" if args.apply else "Mode: DRY-RUN")

    changed = 0
    unchanged = 0
    failed = 0
    for row in rows:
        desired = location_from_row(row)
        label = f"{row.application_id}/{row.device_id}"
        try:
            device = get_device(session, base, row, args.timeout)
            locations = dict(device.get("locations") or {})
            current = dict(locations.get("user") or {})
            if same_location(current, desired):
                print(f"UNCHANGED {label}")
                unchanged += 1
                continue

            changed += 1
            print(
                f"UPDATE {label}: current={json.dumps(current, sort_keys=True)} "
                f"desired={json.dumps(desired, sort_keys=True)}"
            )
            if not args.apply:
                continue

            # Preserve TTN-provided sources (for example gps or network) and
            # replace only the user-managed location.
            locations["user"] = desired
            update_device(session, base, row, locations, args.timeout)
            verified = get_device(session, base, row, args.timeout)
            verified_user = dict((verified.get("locations") or {}).get("user") or {})
            if same_location(verified_user, desired):
                print(f"  APPLIED {label}")
            else:
                print(f"  VERIFY_FAILED {label}: {json.dumps(verified_user, sort_keys=True)}")
                failed += 1
        except requests.RequestException as error:
            print(f"ERROR {label}: {error}", file=sys.stderr)
            failed += 1

    print(f"Summary: changed={changed} unchanged={unchanged} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
