#!/usr/bin/env python3
"""Construct synthetic fonts with 'kern' format 2 (class-based) subtables.

No font files or third-party Python packages are used; every font is a
minimal sfnt built from packed structures.  The generator covers

  * a valid horizontal additive format 2 subtable,
  * an override (coverage bit 3) format 2 subtable,
  * a font mixing format 0 and format 2 subtables,
  * a format 0-only font as a zero-regression control,
  * a font with a truncated class table (FT_Err_Invalid_Table), and
  * a font whose class value indexes past the kerning array
    (FT_Err_Invalid_Offset).

This file is distributed under the FreeType project license, LICENSE.TXT.
"""
from pathlib import Path
import struct
import sys


def checksum(data):
    data += b"\0" * (-len(data) % 4)
    return sum(struct.unpack(">" + "I" * (len(data) // 4), data)) & 0xFFFFFFFF


def cmap_format4():
    # Two segments: U+0041..U+0047 -> glyph 1..7, then the sentinel.
    seg_count = 2
    seg_count_x2 = seg_count * 2
    length = 16 + seg_count_x2 * 4
    sub = struct.pack(
        ">7H",
        4, length, 0, seg_count_x2,
        seg_count_x2 + 2 * 2, 0, seg_count - 1,
    )
    sub += struct.pack(">2H", 0x47, 0xFFFF)              # endCode
    sub += struct.pack(">H", 0)                         # reservedPad
    sub += struct.pack(">2H", 0x41, 0xFFFF)             # startCode
    sub += struct.pack(">2h", 1 - 0x41, 1)              # idDelta
    sub += struct.pack(">2H", 0, 0)                     # idRangeOffset
    return struct.pack(">HHHHI", 0, 1, 3, 1, 12) + sub


def kern_subtable(coverage, body, declared_length=None):
    length = 6 + len(body) if declared_length is None else declared_length
    return struct.pack(">HHH", 0, length, coverage) + body


def fmt2_body(left_classes, right_classes, values, row_width,
              left_first=1, right_first=1):
    """Build the 8-byte format 2 header, two class tables, and the array.

    The three offsets are relative to the start of the enclosing
    subtable, which also contains its 6-byte header preceding this
    body.
    """
    left = struct.pack(">HH", left_first, len(left_classes)) + b"".join(
        struct.pack(">H", v) for v in left_classes)
    right = struct.pack(">HH", right_first, len(right_classes)) + b"".join(
        struct.pack(">H", v) for v in right_classes)
    array = b"".join(struct.pack(">h", v) for v in values)
    header_size = 6
    left_off = header_size + 8
    right_off = left_off + len(left)
    array_off = right_off + len(right)
    header = struct.pack(">HHHH", row_width, left_off, right_off, array_off)
    return header + left + right + array


def fmt0_body(pairs):
    # `pairs` is a list of (left_glyph, right_glyph, value), already sorted.
    # Header: nPairs, searchRange, entrySelector, rangeShift.
    n = len(pairs)
    search_range = 2 * (1 << (n.bit_length() - 1))
    entry_selector = (n.bit_length() - 1) if n else 0
    body = struct.pack(">4H", n, search_range, entry_selector,
                       n * 2 - search_range)
    for left, right, value in pairs:
        body += struct.pack(">HHh", left, right, value)
    return body


def kern_table(subtables):
    return struct.pack(">HH", 0, len(subtables)) + b"".join(subtables)


# The well-formed class layout shared by the format 2 fixtures:
#
#   glyphs 1,3 -> row 0 and glyphs 2,4 -> row 1 (row width 4 bytes)
#   glyphs 1,3 -> column 0 and glyphs 2,4 -> column 2
#   glyph 0 and glyphs 5+ are outside both class ranges and take class 0.
LEFT_CLASSES = [0, 4, 0, 4]
RIGHT_CLASSES = [0, 2, 0, 2]
VALUES = [-10, -20, -30, -40]


def make_font(kern, num_glyphs=8):
    head = struct.pack(">IIIIHHQQhhhhHHhhh", 0x10000, 0x10000, 0, 0x5F0F3CF5,
                       0, 1000, 0, 0, 0, 0, 0, 0, 0, 8, 2, 1, 0)
    hhea = bytearray(36)
    struct.pack_into(">IhhhH", hhea, 0, 0x10000, 800, -200, 0, 500)
    struct.pack_into(">h", hhea, 18, 1)  # caretSlopeRise
    struct.pack_into(">H", hhea, 34, num_glyphs)  # numberOfHMetrics
    maxp = struct.pack(">I14H", 0x10000, num_glyphs, 0, 0, 0, 0, 1, 0, 0, 0,
                       0, 0, 0, 0, 1)
    glyf = b""
    loca = struct.pack(">%dI" % (num_glyphs + 1), *([0] * (num_glyphs + 1)))
    hmtx = b"".join(struct.pack(">Hh", 500, 0) for _ in range(num_glyphs))
    names = [(1, "Kern Format 2 Test"), (2, "Regular"),
             (4, "Kern Format 2 Test Regular"),
             (6, "KernFormat2Test-Regular")]
    records, strings = bytearray(), bytearray()
    for name_id, value in names:
        encoded = value.encode("utf-16-be")
        records += struct.pack(">6H", 3, 1, 0x409, name_id,
                               len(encoded), len(strings))
        strings += encoded
    name = struct.pack(">3H", 0, len(names), 6 + len(records)) + \
        records + strings
    tables = {
        b"cmap": cmap_format4(),
        b"glyf": glyf,
        b"head": head,
        b"hhea": bytes(hhea),
        b"hmtx": hmtx,
        b"kern": kern,
        b"loca": loca,
        b"maxp": maxp,
        b"name": name,
        b"post": struct.pack(">I", 0x30000) + bytes(28),
    }
    count = len(tables)
    power = 1 << (count.bit_length() - 1)
    font = bytearray(struct.pack(">I4H", 0x10000, count, power * 16,
                                 power.bit_length() - 1,
                                 count * 16 - power * 16))
    font += bytes(16 * count)
    head_offset = None
    for index, (tag, data) in enumerate(sorted(tables.items())):
        offset = len(font)
        struct.pack_into(">4sIII", font, 12 + 16 * index, tag,
                         checksum(data), offset, len(data))
        font += data + bytes(-len(data) % 4)
        if tag == b"head":
            head_offset = offset
    struct.pack_into(">I", font, head_offset + 8,
                     (0xB1B0AFBA - checksum(font)) & 0xFFFFFFFF)
    assert checksum(font) == 0xB1B0AFBA
    return bytes(font)


def build_fonts():
    # 1. Single additive format 2 subtable (coverage 0x0201).
    add_body = fmt2_body(LEFT_CLASSES, RIGHT_CLASSES, VALUES, row_width=4)
    kern_add = kern_table([kern_subtable(0x0201, add_body)])

    # 2. Additive then override (0x0209): the second subtable wins.
    #    It has a single-cell array, so every pair gets the value -15.
    override_body = fmt2_body([0, 0], [0, 0], [-15], row_width=2)
    kern_override = kern_table([
        kern_subtable(0x0201, add_body),
        kern_subtable(0x0209, override_body),
    ])

    # 3. Mixed format 0 plus format 2.  The format 0 pairs use glyph 5,
    # which is outside the format 2 class ranges, so the two paths are
    # exercised independently.
    f0_body = fmt0_body([(1, 5, -100), (5, 4, -50)])
    kern_mixed = kern_table([
        kern_subtable(0x0001, f0_body),
        kern_subtable(0x0201, add_body),
    ])

    # 4. Format 0 only: regression control for the old path.
    kern_f0 = kern_table([kern_subtable(0x0001, f0_body)])
    # 5. Truncated class table: the right class table's nGlyphs count
    # claims far more entries than the subtable can hold.  The main
    # header offsets stay valid, so this fails the class-table size
    # check specifically (FT_Err_Invalid_Table).
    truncated_body = bytearray(fmt2_body(LEFT_CLASSES, RIGHT_CLASSES,
                                         VALUES, row_width=4))
    right_hdr = 8 + 4 + 2 * len(LEFT_CLASSES)  # body offset of right table
    struct.pack_into(">H", truncated_body, right_hdr + 2, 0x4000)
    kern_truncated = kern_table(
        [kern_subtable(0x0201, bytes(truncated_body))])

    # 6. Left class value 8 indexes past the 8-byte kerning array.
    oob_body = fmt2_body([0, 8], RIGHT_CLASSES, [0, 0, 0, 0], row_width=4)
    kern_oob = kern_table([kern_subtable(0x0201, oob_body)])

    # 7. Two format 2 subtables with no format 0, so the whole table is
    # read on demand from the stream.  The first is vertical (coverage
    # 0x0200) and must be ignored; the second is a normal horizontal
    # additive table with array [-7, -9].
    second_body = fmt2_body(LEFT_CLASSES, RIGHT_CLASSES,
                            [-7, -9, -7, -9], row_width=4)
    kern_stream = kern_table([
        kern_subtable(0x0200, add_body),  # vertical, ignored
        kern_subtable(0x0201, second_body),
    ])

    return {
        "kern2-add.ttf": make_font(kern_add),
        "kern2-override.ttf": make_font(kern_override),
        "kern2-mixed.ttf": make_font(kern_mixed),
        "kern0-only.ttf": make_font(kern_f0),
        "kern2-truncated.ttf": make_font(kern_truncated),
        "kern2-oob-index.ttf": make_font(kern_oob),
        "kern2-stream.ttf": make_font(kern_stream),
    }


if __name__ == "__main__":
    if len(sys.argv) != 8:
        raise SystemExit(
            "usage: make-fonts.py add override mixed f0 truncated oob "
            "stream")
    fonts = build_fonts()
    for output, key in zip(sys.argv[1:], [
            "kern2-add.ttf", "kern2-override.ttf", "kern2-mixed.ttf",
            "kern0-only.ttf", "kern2-truncated.ttf",
            "kern2-oob-index.ttf", "kern2-stream.ttf"]):
        Path(output).write_bytes(fonts[key])
        print(f"{key}: {len(fonts[key])} bytes -> {Path(output).name}")
