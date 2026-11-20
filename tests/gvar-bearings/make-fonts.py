#!/usr/bin/env python3
"""Hand-build variable TrueType fonts with gvar side-bearing deltas.

Only the Python standard library is used.  The generated fonts exercise the
gvar phantom-point path that carries lsb/rsb/tsb/bsb and advance deltas:

  * `gvar-bearings.ttf`        -- fvar + gvar, one shared peak tuple and a
                                   glyph-level shared packed point run
  * `gvar-embedded.ttf`        -- same deltas through an embedded private
                                   peak tuple (no shared tuples)
  * `gvar-privatepoints.ttf`   -- private per-tuple packed point numbers
                                   instead of a glyph-level shared run
  * `gvar-nogvar.ttf`          -- identical skeleton, gvar removed
  * `gvar-hvar.ttf`            -- adds HVAR/VVAR so advance deltas must be
                                   ignored while bearing deltas still apply
  * `gvar-bad-*.ttf`           -- malformed gvar variants, each rejected with
                                   FT_Err_Invalid_Table

Glyph layout (font units, upem 1000):
  .notdef -- empty
  A       -- triangle (100,0) (400,0) (250,500), 3 outline points
  V       -- rectangle (50,50) (350,50) (350,250) (50,250), 4 outline points

The wght axis ranges 100..900, default 400; normalized coordinate 1.0
selects the full delta set.  gvar tuples always carry the four phantom
points explicitly, because IUP interpolation never reaches them.

Distributed under the FreeType project license, LICENSE.TXT.
"""
from pathlib import Path
import struct
import sys


# --------------------------------------------------------------------------
# SFNT scaffolding, shared with tests/varc/make-hvvar-fonts.py conventions
# --------------------------------------------------------------------------

def checksum(data):
    data += b"\0" * (-len(data) % 4)
    return sum(struct.unpack(">" + "I" * (len(data) // 4), data)) & 0xFFFFFFFF


def sfnt(tables):
    count = len(tables)
    power = 1 << (count.bit_length() - 1)
    font = bytearray(struct.pack(
        ">I4H", 0x10000, count, power * 16,
        power.bit_length() - 1, count * 16 - power * 16))
    font += bytes(16 * count)
    head_offset = None
    for index, (tag, data) in enumerate(sorted(tables.items())):
        offset = len(font)
        struct.pack_into(">4sIII", font, 12 + 16 * index,
                         tag, checksum(data), offset, len(data))
        font += data + bytes(-len(data) % 4)
        if tag == b"head":
            head_offset = offset
    struct.pack_into(
        ">I", font, head_offset + 8,
        (0xB1B0AFBA - checksum(font)) & 0xFFFFFFFF)
    return bytes(font)


def make_head():
    # version, fontRev, checksumAdj, magic, flags, upem, created, modified,
    # xMin,yMin,xMax,yMax, macStyle, lowestRecPPEM, fontDirectionHint,
    # indexToLocFormat, glyphDataFormat
    return struct.pack(">IIIIHHQQhhhhHHhhh",
                       0x10000, 0x10000, 0, 0x5F0F3CF5,
                       0, 1000, 0, 0,
                       50, 0, 400, 500, 0, 8, 2, 1, 0)


def make_hhea():
    h = bytearray(36)
    struct.pack_into(">IhhhH", h, 0, 0x10000, 800, -200, 0, 600)
    struct.pack_into(">h", h, 18, 1)   # caretSlopeRise
    struct.pack_into(">H", h, 34, 3)   # numberOfHMetrics
    return bytes(h)


def make_vhea():
    v = bytearray(36)
    struct.pack_into(">IhhhHhhh", v, 0, 0x10000, 800, -200, 0,
                     1000, 0, 0, 500)
    struct.pack_into(">h", v, 18, 1)   # caretSlopeRise
    struct.pack_into(">H", v, 34, 3)   # numberOfVMetrics
    return bytes(v)


def make_maxp(num_glyphs):
    # version 1.0 with the 14 legacy UShort fields
    return struct.pack(">I14H", 0x10000, num_glyphs,
                       0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1)


def make_cmap():
    # format 4, two segments: 'A'(0x41)->gid 1, 'V'(0x56)->gid 2, sentinel.
    # With idDelta 0 and idRangeOffset pointing at the following UShort array
    # [1, 2], glyph id = charCode offset + array value.
    sub = struct.pack(">7H", 4, 32, 0, 4, 4, 1, 0)
    sub += struct.pack(">4H", 0x56, 0xFFFF, 0, 0x41)  # endCode + pad + start
    sub += struct.pack(">2h", 0, 0)                   # idDelta
    sub += struct.pack(">2H", 4, 0)                   # idRangeOffset (2 slots)
    sub += struct.pack(">2H", 1, 2)                   # glyph id array
    return struct.pack(">HHHHI", 0, 1, 3, 1, 12) + sub


def make_name():
    names = [(1, "GVar Bearings"), (2, "Regular"),
             (4, "GVar Bearings Regular"),
             (6, "GVarBearings-Regular"), (256, "Weight")]
    records, strings = bytearray(), bytearray()
    for name_id, value in names:
        encoded = value.encode("utf-16-be")
        records += struct.pack(">6H", 3, 1, 0x409, name_id,
                               len(encoded), len(strings))
        strings += encoded
    return struct.pack(">3H", 0, len(names), 6 + len(records)) + \
        records + strings


def make_fvar():
    # header: major/minor, axesArrayOffset, reserved, axisCount, axisSize,
    # instanceCount, instanceSize
    out = struct.pack(">8H", 1, 0, 16, 2, 1, 20, 0, 8)
    # axis: tag, min, def, max as 16.16 Fixed design coordinates,
    # flags, nameID
    out += struct.pack(">4siiiHH", b"wght",
                       100 << 16, 400 << 16, 900 << 16, 0, 256)
    return out


def make_post():
    return struct.pack(">I", 0x30000) + bytes(28)


# --------------------------------------------------------------------------
# glyf / loca
# --------------------------------------------------------------------------

def simple_glyph(bbox, end_pts, xs, ys):
    """Serialize a simple glyph from absolute coordinate lists.

    Coordinates are encoded as 16-bit signed deltas (flags with neither
    X_SHORT nor Y_SHORT set, so the following values are int16 deltas).
    """
    out = struct.pack(">5h", 1, *bbox)
    out += struct.pack(">" + "H" * len(end_pts), *end_pts)
    out += struct.pack(">h", 0)                  # instructionLength
    flag = 0x01                                  # ON_CURVE, long coords
    out += bytes([flag] * len(xs))
    px = py = 0
    for x in xs:
        out += struct.pack(">h", x - px)
        px = x
    for y in ys:
        out += struct.pack(">h", y - py)
        py = y
    if len(out) % 2:
        out += b"\0"
    return out


def make_glyf():
    empty = b""
    tri = simple_glyph(
        (100, 0, 400, 500), [2],
        [100, 400, 250], [0, 0, 500])
    rect = simple_glyph(
        (50, 50, 350, 250), [3],
        [50, 350, 350, 50], [50, 50, 250, 250])
    chunks = [empty, tri, rect]
    glyf = bytearray()
    offsets = []
    for chunk in chunks:
        offsets.append(len(glyf))
        glyf += chunk
        if len(chunk) % 2:
            glyf += b"\0"
    offsets.append(len(glyf))
    loca = struct.pack(">" + "I" * len(offsets), *offsets)
    return bytes(glyf), loca


def make_hmtx():
    # (advanceWidth, leftSideBearing) per glyph
    return struct.pack(">HhHhHh", 500, 0, 600, 100, 500, 50)


def make_vmtx():
    # (advanceHeight, topSideBearing) per glyph
    return struct.pack(">HhHhHh", 1000, 300, 1000, 300, 800, 550)


# --------------------------------------------------------------------------
# gvar packed encodings
# --------------------------------------------------------------------------

def packed_points(points):
    """Encode a packed point-number array.

    Layout: a leading count byte (0x00 means the all-points run), then one
    run header per run whose low seven bits hold (run length - 1), followed
    by the run's point deltas as single bytes.  These fixtures only need a
    single byte-delta run per glyph.
    """
    if points is None:
        # zero count => deltas apply to every point in the glyph
        return b"\x00"
    n = len(points)
    out = bytearray([n])
    if n:
        assert n <= 0x80
        out.append(n - 1)                 # one run, byte deltas
        prev = 0
        for p in points:
            d = p - prev
            prev = p
            assert 0 <= d <= 0xFF
            out.append(d)
    return bytes(out)


def packed_deltas(values):
    """Encode one axis of packed deltas into 8-bit runs.

    A run header's low six bits hold (run length - 1); bit 0x80 marks a
    zero-delta run with no following values, bit 0x40 marks 16-bit signed
    values.  These fixtures fit a single run per axis.
    """
    n = len(values)
    assert 1 <= n <= 0x40
    header = n - 1
    if all(v == 0 for v in values):
        return bytes([0x80 | header])      # DELTAS_ARE_ZERO
    if all(-128 <= v <= 127 for v in values):
        return bytes([header]) + bytes(v & 0xFF for v in values)
    if all(-32768 <= v <= 32767 for v in values):
        out = bytearray([0x40 | header])
        for v in values:
            out += struct.pack(">h", v)
        return bytes(out)
    raise ValueError("delta out of range")


def _tuple_header_extra(flags):
    # Embedded/intermediate coordinate bytes follow the 4-byte tuple header;
    # they are part of the header region, so count them into offsetToData.
    extra = 0
    if flags & 0x8000:                     # EMBEDDED_PEAK_TUPLE
        extra += 2
    if flags & 0x4000:                     # INTERMEDIATE_TUPLE
        extra += 4
    return extra


def glyph_variation(peak_embedded, intermediate, point_indices,
                    dx, dy, point_mode):
    """Build one tuple header and its point/delta payload separately.

    Returns `(flags, coord_bytes, point_bytes, delta_bytes)`.
    `coord_bytes` holds embedded/intermediate coordinates that follow the
    fixed 4-byte tuple header; `point_bytes` is the private packed point
    run (empty in shared-point mode); `delta_bytes` is the x/y delta runs.
    The tuple's dataSize covers point_bytes + delta_bytes.
    """
    flags = 0
    coord = bytearray()

    if peak_embedded:
        flags |= 0x8000                   # EMBEDDED_PEAK_TUPLE
        coord += struct.pack(">h", 0x4000)  # peak = 1.0 normalized (F2Dot14)
        if intermediate:
            flags |= 0x4000               # INTERMEDIATE_TUPLE
            coord += struct.pack(">hh", 0, 0x4000)
    # else: shared tuple index 0; the peak lives in gvar's shared-tuple array

    if point_mode == "private":
        flags |= 0x2000                   # GX_TI_PRIVATE_POINT_NUMBERS
        point_bytes = packed_points(point_indices)
    else:
        point_bytes = b""
    delta_bytes = packed_deltas(dx) + packed_deltas(dy)

    data_size = len(point_bytes) + len(delta_bytes)
    tuple_header = struct.pack(">HH", data_size, flags) + bytes(coord)
    return flags, tuple_header, point_bytes, delta_bytes


def glyph_table(spec, share_points):
    """Assemble one glyph variation table (outer header + tuple + data).

    `spec` is (peak_embedded, intermediate, point_indices, dx, dy).  The
    outer glyph-level header holds tupleVariationCount -- OR-ed with
    GX_TC_TUPLES_SHARE_POINT_NUMBERS only when a glyph-level shared packed
    point run is present -- and offsetToData, the distance from the glyph
    table start to the variation data (the shared point run, if any, else
    the tuple's private point/delta payload).
    """
    embedded, intermediate, points, dx, dy = spec
    flags, tuple_header, point_bytes, delta_bytes = glyph_variation(
        embedded, intermediate, points, dx, dy,
        "shared" if share_points else "private")

    shared_run = packed_points(points) if share_points else b""

    # offsetToData skips the 4-byte outer header and the whole tuple header
    # (its 4 fixed bytes plus any embedded/intermediate coordinates).
    offset_to_data = 4 + 4 + _tuple_header_extra(flags)

    count = 1 | (0x8000 if share_points else 0)
    out = struct.pack(">HH", count, offset_to_data)
    out += tuple_header
    out += shared_run
    out += point_bytes
    out += delta_bytes
    return out


def make_gvar(glyph_specs, *, shared_tuples=True, share_points=False):
    """Assemble a gvar table.

    `glyph_specs` maps glyph index to
    (peak_embedded, intermediate, point_indices, dx, dy); glyphs without an
    entry get a zero-length variation (equal consecutive offsets).  When
    `share_points` is set every varying glyph uses a glyph-level shared
    packed point run (the caller guarantees the point sets are compatible).
    """
    num_glyphs = 3
    # shared tuple: one F2Dot14 coordinate per axis
    shared = struct.pack(">h", 0x4000) if shared_tuples else b""

    header_size = 20
    # glyph offsets (USHORT form, scaled by 2) sit right after the header
    offsets_bytes_len = (num_glyphs + 1) * 2
    # the shared (global) tuple coordinates follow the glyph offset array
    offset_to_coord = header_size + offsets_bytes_len
    offset_to_data = header_size + offsets_bytes_len + len(shared)

    bodies = []
    for gid in range(num_glyphs):
        if gid in glyph_specs:
            body = glyph_table(glyph_specs[gid], share_points)
        else:
            body = b""
        # Short (USHORT) glyph offsets encode half-offsets, so every
        # glyph variation table must occupy an even number of bytes.
        if len(body) % 2:
            body += b"\0"
        bodies.append(body)
    # Short (USHORT) glyph offsets are relative to the variation data
    # start and stored at half scale; FreeType adds the table-absolute
    # data position back when reading.
    raw_offsets = [0]
    for body in bodies:
        raw_offsets.append(raw_offsets[-1] + len(body))
    assert raw_offsets[-1] % 2 == 0, "short offsets need even data sizes"
    offset_table = struct.pack(
        ">" + "H" * (num_glyphs + 1),
        *[o // 2 for o in raw_offsets])

    # gvar header (20 bytes): version(4) axisCount(2) globalCoordCount(2)
    # offsetToCoord(4) glyphCount(2) flags(2) offsetToData(4).
    head = struct.pack(
        ">IHHIHHI",
        0x00010000,                        # version
        1,                                 # axisCount
        1 if shared_tuples else 0,         # globalCoordCount
        offset_to_coord,                   # offsetToCoord
        num_glyphs,                        # glyphCount
        0,                                 # flags: short offsets
        offset_to_data)                    # offsetToData
    assert len(head) == header_size

    out = head + offset_table + shared
    for body in bodies:
        out += body
    return out


# --------------------------------------------------------------------------
# Delta design
# --------------------------------------------------------------------------

# Glyph A: 3 outline points + phantoms pp1..pp4 (indices 3..6), 7 points.
# Full-point run; the outline shifts by (20,4) at peak and the phantoms move
# by pp1 +=40, pp2 +=60 horizontally (advance +20, lsb changes) and
# pp3 +=10, pp4 -=30 vertically (vadvance +40).
A_POINTS = None                          # all-points run
A_DX = [20, 20, 20, 40, 60, 0, 0]
A_DY = [4, 4, 4, 0, 0, 10, -30]

# Glyph V: 4 outline points + 4 phantoms, 8 points.  Also a full-point run
# so the glyph-level shared point run (the all-points marker) is identical
# for both varying glyphs.  The outline is static here; only the vertical
# phantoms move (pp3 is index 6, pp4 index 7), isolating the bearing/
# advance path from outline interpolation.
V_POINTS = None                          # all-points run
V_DX = [0, 0, 0, 0, 0, 0, 0, 0]
V_DY = [0, 0, 0, 0, 0, 0, 20, -40]


def build_specs(embedded, intermediate=False):
    return {
        1: (embedded, intermediate, A_POINTS, A_DX, A_DY),
        2: (embedded, intermediate, V_POINTS, V_DX, V_DY),
    }


def base_tables(with_gvar=None, hvar=False, vvar=False):
    glyf, loca = make_glyf()
    tables = {
        b"cmap": make_cmap(),
        b"fvar": make_fvar(),
        b"glyf": glyf,
        b"head": make_head(),
        b"hhea": make_hhea(),
        b"hmtx": make_hmtx(),
        b"loca": loca,
        b"maxp": make_maxp(3),
        b"name": make_name(),
        b"post": make_post(),
        b"vhea": make_vhea(),
        b"vmtx": make_vmtx(),
    }
    if with_gvar is not None:
        tables[b"gvar"] = with_gvar
    if hvar or vvar:
        tables.update(make_metric_tables(hvar, vvar))
    return tables


def make_metric_tables(hvar, vvar):
    # ItemVariationStore, format 1 with one region (wght peak 1.0) and one
    # VarData row of shorts giving the implicit glyph-to-delta map.  The
    # byte layout follows FreeType's tt_var_load_item_variation_store parser
    # and tests/varc/make-hvvar-fonts.py.
    def store(deltas):
        # These fixtures use single-region delta sets whose per-glyph values
        # all fit in a signed byte, so shortDeltaCount is 0 and each delta
        # set is one INT8.  FreeType reads itemCount*(sdc+ric) values.
        assert all(-128 <= d <= 127 for d in deltas)
        n = len(deltas)
        out = bytearray()
        # VarStore header (12 bytes): format(H), VarRegionListOffset(12),
        # VarDataCount(H=1), VarDataOffsetArray[0](22).
        out += struct.pack(">HIHI", 1, 12, 1, 22)
        # VarRegionList at offset 12: axisCount(H), regionCount(H); the
        # region axis records follow immediately (no separate offset field).
        out += struct.pack(">HH", 1, 1)
        # VarRegionAxis (6 bytes): start, peak, end as F2Dot14.
        out += struct.pack(">hhh", 0, 0x4000, 0x4000)
        # VarData at offset 22: itemCount(H), shortDeltaCount(H=0),
        # regionIndexCount(H=1), regionIndex[0](H=0), then one signed-byte
        # delta per glyph.
        out += struct.pack(">HHH", n, 0, 1)
        out += struct.pack(">H", 0)
        out += bytes(d & 0xFF for d in deltas)
        return bytes(out)

    out = {}
    if hvar:
        # major, minor, itemVariationStoreOffset, lsbMap, rsbMap
        out[b"HVAR"] = struct.pack(">HH4I", 1, 0, 20, 0, 0, 0) + \
                       store([70, 70, 0])
    if vvar:
        # major, minor, itemVariationStoreOffset, advHeightMap,
        # tsbMap, bsbMap
        out[b"VVAR"] = struct.pack(">HH5I", 1, 0, 24, 0, 0, 0, 0) + \
                       store([0, 0, 90])
    return out


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    # Main fixture: shared peak tuple plus a glyph-level shared packed
    # point run (the dominant real-world encoding).
    shared_gvar = make_gvar(
        build_specs(embedded=False), share_points=True)
    # Embedded private peak tuple, still with glyph-level shared points.
    embedded_gvar = make_gvar(
        build_specs(embedded=True), shared_tuples=False,
        share_points=True)
    # Private point numbers carried inside each tuple (no glyph-level
    # shared run); glyph A names a sparse set to also exercise IUP.
    private_specs = {
        1: (False, False, [0, 1, 2, 3, 4, 5, 6], A_DX, A_DY),
        2: (False, False, list(range(8)), V_DX, V_DY),
    }
    private_gvar = make_gvar(private_specs, share_points=False)

    (out / "gvar-bearings.ttf").write_bytes(
        sfnt(base_tables(shared_gvar)))
    (out / "gvar-embedded.ttf").write_bytes(
        sfnt(base_tables(embedded_gvar)))
    (out / "gvar-privatepoints.ttf").write_bytes(
        sfnt(base_tables(private_gvar)))
    (out / "gvar-nogvar.ttf").write_bytes(
        sfnt(base_tables(None)))
    (out / "gvar-hvar.ttf").write_bytes(
        sfnt(base_tables(shared_gvar, hvar=True, vvar=True)))

    # Malformed variants: every file stays a structurally valid sfnt so the
    # face opens, but the gvar table is internally corrupt and must fail at
    # blend setup with FT_Err_Invalid_Table rather than being silently used.
    good = bytearray(sfnt(base_tables(shared_gvar)))
    gvar_off, gvar_len = find_table(good, b"gvar")

    # Unsupported gvar version number.
    bad_version = bytearray(good)
    bad_version[gvar_off:gvar_off + 4] = b"\x00\x00\x00\x02"
    (out / "gvar-bad-version.ttf").write_bytes(bytes(bad_version))

    # Axis count disagreeing with the fvar axis count.
    bad_axis = bytearray(good)
    bad_axis[gvar_off + 4:gvar_off + 6] = b"\x00\x09"   # axisCount = 9
    (out / "gvar-bad-axis.ttf").write_bytes(bytes(bad_axis))

    # GlyphCount far beyond the table's offset array: the declared offset
    # array length overruns the table, rejected while loading gvar.
    bad_count = bytearray(good)
    bad_count[gvar_off + 12:gvar_off + 14] = b"\x20\x00"  # glyphCount 8192
    (out / "gvar-bad-count.ttf").write_bytes(bytes(bad_count))

    # A glyph variation table whose declared data size runs past the end of
    # the gvar table.  The outer sfnt and gvar header stay intact, so the
    # fault is first detected when the glyph deltas are read.
    bad_oob = bytearray(good)
    hdr = struct.unpack(">IHHIHHI",
                        bytes(bad_oob[gvar_off:gvar_off + 20]))
    data_start = hdr[6]
    # first glyph variation header lives at the data start; inflate its
    # tupleDataSize (the USHORT right after tupleVariationCount).
    struct.pack_into(">H", bad_oob, gvar_off + data_start + 2, 0xFFFF)
    (out / "gvar-bad-tuplesize.ttf").write_bytes(bytes(bad_oob))

    print("wrote gvar fixtures to", out)


def find_table(font, tag):
    count = struct.unpack_from(">H", font, 4)[0]
    for i in range(count):
        t, _, offset, length = struct.unpack_from(
            ">4sIII", font, 12 + 16 * i)
        if t == tag:
            return offset, length
    raise KeyError(tag)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: make-gvar-fonts.py output-dir")
    main(sys.argv[1])
