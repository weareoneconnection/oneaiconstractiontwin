"""Minimal JPEG EXIF reader.

A site photograph's value as evidence depends on *when* it was taken, and the upload
time is not that — photos reach the office hours or days later. The capture time is in
the file, so it is read from the file.

This parses only the two tags that matter (DateTimeOriginal and GPS position) directly
from the APP1 segment, rather than adding an imaging dependency to the API image for
two fields. Anything it cannot parse returns None, and the caller falls back to the
upload time and records which one it used.
"""

from __future__ import annotations

import struct
from datetime import datetime
from typing import Any

DATE_TIME_ORIGINAL = 0x9003
DATE_TIME = 0x0132
EXIF_IFD_POINTER = 0x8769
GPS_IFD_POINTER = 0x8825
GPS_LAT_REF, GPS_LAT, GPS_LON_REF, GPS_LON = 0x0001, 0x0002, 0x0003, 0x0004

TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}


def _read_ifd(data: bytes, offset: int, endian: str) -> dict[int, tuple[int, int, int]]:
    """Return {tag: (type, count, value_offset)} for one IFD."""
    entries: dict[int, tuple[int, int, int]] = {}
    if offset + 2 > len(data):
        return entries
    (count,) = struct.unpack_from(endian + "H", data, offset)
    position = offset + 2
    for _ in range(min(count, 512)):
        if position + 12 > len(data):
            break
        tag, field_type, length = struct.unpack_from(endian + "HHI", data, position)
        value_offset = position + 8
        size = TYPE_SIZES.get(field_type, 1) * length
        if size > 4:
            (pointer,) = struct.unpack_from(endian + "I", data, position + 8)
            value_offset = pointer
        entries[tag] = (field_type, length, value_offset)
        position += 12
    return entries


def _ascii(data: bytes, offset: int, length: int) -> str:
    if offset < 0 or offset + length > len(data):
        return ""
    return data[offset:offset + length].split(b"\x00")[0].decode("ascii", errors="replace").strip()


def _rationals(data: bytes, offset: int, count: int, endian: str) -> list[float]:
    values: list[float] = []
    for index in range(count):
        position = offset + index * 8
        if position + 8 > len(data):
            break
        numerator, denominator = struct.unpack_from(endian + "II", data, position)
        values.append(numerator / denominator if denominator else 0.0)
    return values


def _degrees(parts: list[float], reference: str) -> float | None:
    if len(parts) < 3:
        return None
    value = parts[0] + parts[1] / 60 + parts[2] / 3600
    return -value if reference.upper() in ("S", "W") else value


def read_exif(raw: bytes) -> dict[str, Any]:
    """Extract capture time and GPS. Returns {} for anything unparseable."""
    result: dict[str, Any] = {}
    if len(raw) < 4 or raw[:2] != b"\xff\xd8":  # not a JPEG
        return result

    # Walk the JPEG segments to find APP1/Exif.
    position = 2
    exif = b""
    while position + 4 <= len(raw):
        if raw[position] != 0xFF:
            break
        marker = raw[position + 1]
        (length,) = struct.unpack_from(">H", raw, position + 2)
        segment = raw[position + 4: position + 2 + length]
        if marker == 0xE1 and segment[:6] == b"Exif\x00\x00":
            exif = segment[6:]
            break
        if marker == 0xDA:  # start of scan: no metadata beyond here
            break
        position += 2 + length

    if len(exif) < 8:
        return result

    endian = "<" if exif[:2] == b"II" else ">" if exif[:2] == b"MM" else ""
    if not endian:
        return result
    (first_ifd,) = struct.unpack_from(endian + "I", exif, 4)
    root = _read_ifd(exif, first_ifd, endian)

    def _tag_datetime(entries: dict[int, tuple[int, int, int]], tag: int) -> datetime | None:
        entry = entries.get(tag)
        if not entry:
            return None
        text = _ascii(exif, entry[2], entry[1])
        for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None

    def _sub_ifd(entries: dict[int, tuple[int, int, int]], tag: int) -> dict[int, tuple[int, int, int]]:
        """Follow an IFD pointer. The pointer is a LONG, so it sits inline in the entry."""
        entry = entries.get(tag)
        if not entry or entry[2] + 4 > len(exif):
            return {}
        (offset,) = struct.unpack_from(endian + "I", exif, entry[2])
        return _read_ifd(exif, offset, endian)

    # DateTimeOriginal is when the shutter fired; DateTime can be a later edit, so it is
    # only the fallback.
    taken = _tag_datetime(_sub_ifd(root, EXIF_IFD_POINTER), DATE_TIME_ORIGINAL) or _tag_datetime(root, DATE_TIME)
    if taken:
        result["taken_at"] = taken

    gps = _sub_ifd(root, GPS_IFD_POINTER)
    if gps:
        lat_ref = _ascii(exif, gps[GPS_LAT_REF][2], gps[GPS_LAT_REF][1]) if GPS_LAT_REF in gps else ""
        lon_ref = _ascii(exif, gps[GPS_LON_REF][2], gps[GPS_LON_REF][1]) if GPS_LON_REF in gps else ""
        latitude = _degrees(_rationals(exif, gps[GPS_LAT][2], 3, endian), lat_ref) if GPS_LAT in gps else None
        longitude = _degrees(_rationals(exif, gps[GPS_LON][2], 3, endian), lon_ref) if GPS_LON in gps else None
        if latitude is not None and longitude is not None:
            result["gps"] = {"latitude": round(latitude, 6), "longitude": round(longitude, 6)}

    return result
