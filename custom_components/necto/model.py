"""Parse telemetry observed in Necto's device-list page.

The upstream website format is undocumented and may change.
"""

from dataclasses import dataclass
from datetime import datetime
import math


@dataclass(frozen=True)
class Device:
    device_id: str
    name: str
    temperature: float | None
    temperature_unit: str | None
    humidity: float | None
    offline: bool | None
    powered_off: bool | None
    last_report: datetime | None
    event: str | None


def _number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


def _boolean(value):
    return value if isinstance(value, bool) else None


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def parse_devices(page):
    """Parse one page of Inertia device-list props; callers must handle paging."""
    try:
        props = page["props"]
        records = props["devices"]["data"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Not a Necto device-list response") from exc
    if not isinstance(records, list):
        raise ValueError("Not a Necto device-list response")
    user = props.get("user")
    if user is None:
        user = {}
    if not isinstance(user, dict):
        raise ValueError("Malformed account metadata")
    meta = user.get("meta")
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise ValueError("Malformed account metadata")
    unit = meta.get("unit")
    if unit not in ("f", "c"):
        unit = None
    result = []
    for record in records:
        if not isinstance(record, dict) or not record.get("device_id"):
            raise ValueError("Device is missing its identifier")
        report = record.get("latest_report")
        if report is None:
            report = {}
        if not isinstance(report, dict):
            raise ValueError("Device report is malformed")
        result.append(Device(
            device_id=str(record["device_id"]), name=record.get("name") or "Necto",
            temperature=_number(report.get("temp_val")), temperature_unit=unit,
            humidity=_number(report.get("humi_val")), offline=_boolean(record.get("is_offline")),
            powered_off=_boolean(record.get("is_powered_off")),
            last_report=_timestamp(record.get("latest_report_at")),
            event=report.get("event") if isinstance(report.get("event"), str) and len(report["event"]) <= 255 else None,
        ))
    return result


async def fetch_devices(client):
    """Fetch every page through an authenticated client supplied by the caller.

    Follow only page numbers, never a server-provided URL, to avoid credential
    leakage.
    """
    devices = {}
    page_number = 1
    expected_last = None
    while True:
        page = await client.get_device_page(page_number)
        try:
            meta = page["props"]["devices"]["meta"]
            current, last = meta["current_page"], meta["last_page"]
        except (KeyError, TypeError) as exc:
            raise ValueError("Missing pagination metadata") from exc
        if (type(current) is not int or type(last) is not int or
                current != page_number or not 1 <= last <= 100 or
                current > last or (expected_last is not None and last != expected_last)):
            raise ValueError("Inconsistent pagination metadata")
        expected_last = last
        for device in parse_devices(page):
            if device.device_id in devices:
                raise ValueError("Duplicate device identifier across pages")
            devices[device.device_id] = device
        if page_number == last:
            return devices
        page_number += 1
