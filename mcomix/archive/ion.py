"""Amazon Ion 1.0, in its binary encoding, as far as reading it goes.

A Kindle KFX book (kfx.py) keeps everything but the bytes of its
pictures as Ion: the reading order, the pages, what each picture is
and where its bytes are.  Written from Amazon's public specification,
"Ion Binary Encoding" and "Ion Symbols" at
https://amazon-ion.github.io/ion-docs/.

A value is read into Python's own types: null of any type is None, a
bool, int, float or string is one of Python's, a decimal is a
decimal.Decimal, a list is a list and an S-expression a tuple, a blob
or clob is bytes, and a struct is a dict from each field name's symbol
ID to the field's value.  A symbol is a Symbol, its ID: the text is in
a symbol table, which is the caller's to keep.  Annotations are dropped,
leaving the value they annotate.
"""

import decimal
import struct

#: How every binary Ion stream begins: Ion 1.0's version marker.
VERSION_MARKER = b'\xe0\x01\x00\xea'

#: How deep lists and structs may nest.  Each level takes a byte at the
#: least, so a hostile file could otherwise go as deep as it is long.
_MAX_DEPTH = 100


class IonError(ValueError):
    """The data is not Ion 1.0 in its binary encoding."""


class Symbol(int):
    """A symbol, by its ID."""

    def __repr__(self) -> str:
        return '$%d' % self


class Timestamp(bytes):
    """A timestamp, as its representation stands: nothing here reads
    the date out of one."""


#: What a NOP pad reads as, where a value would have been.
_PAD = object()


def loads(data: bytes) -> object:
    """The one value of the binary Ion stream <data>.

    The stream starts with the version marker, and holds that value and
    nothing else but padding and further version markers.  IonError
    where it does not, or anything in it is malformed.
    """
    if not data.startswith(VERSION_MARKER):
        raise IonError('not binary Ion 1.0')
    end = len(data)
    pos = len(VERSION_MARKER)
    values = []
    while pos < end:
        if data.startswith(VERSION_MARKER, pos):
            pos += len(VERSION_MARKER)
            continue
        value, pos = _value(data, pos, end, 0)
        if value is not _PAD:
            values.append(value)
    if len(values) != 1:
        raise IonError('%d values where one was expected' % len(values))
    return values[0]


def _var_uint(data: bytes, pos: int, end: int) -> tuple[int, int]:
    """The VarUInt at <pos>, and where it ends: seven bits an octet,
    most significant first, the high bit set on the last."""
    value = 0
    while True:
        if pos >= end:
            raise IonError('truncated')
        octet = data[pos]
        pos += 1
        value = (value << 7) | (octet & 0x7F)
        if octet & 0x80:
            return value, pos


def _var_int(data: bytes, pos: int, end: int) -> tuple[int, int]:
    """The VarInt at <pos>, and where it ends: a VarUInt whose first
    octet gives up its second-highest bit to the sign."""
    if pos >= end:
        raise IonError('truncated')
    octet = data[pos]
    pos += 1
    negative = octet & 0x40
    value = octet & 0x3F
    while not octet & 0x80:
        if pos >= end:
            raise IonError('truncated')
        octet = data[pos]
        pos += 1
        value = (value << 7) | (octet & 0x7F)
    return (-value if negative else value), pos


def _int(field: bytes) -> tuple[bool, int]:
    """Whether the Int <field> is negative, and its magnitude: a sign
    bit, then the magnitude, big-endian."""
    if not field:
        return False, 0
    value = int.from_bytes(field, 'big')
    sign = 1 << (8 * len(field) - 1)
    return bool(value & sign), value & (sign - 1)


def _decimal(data: bytes, pos: int, end: int) -> decimal.Decimal:
    """The decimal whose representation runs from <pos> to <end>: its
    exponent, a VarInt, then its coefficient, an Int."""
    exponent, pos = _var_int(data, pos, end)
    negative, coefficient = _int(data[pos:end])
    digits = tuple(int(digit) for digit in str(coefficient))
    return decimal.Decimal((int(negative), digits, exponent))


def _value(data: bytes, pos: int, end: int, depth: int) -> tuple[object, int]:
    """The value at <pos>, which has to end by <end>, and where it ends;
    _PAD for a NOP pad.  Annotations are read past."""
    if pos >= end:
        raise IonError('truncated')
    descriptor = data[pos]
    pos += 1
    code, length = descriptor >> 4, descriptor & 0x0F

    if code == 0xF:
        raise IonError('reserved type code 0xF')
    if length == 15:
        if code == 0xE:
            raise IonError('null annotation wrapper')
        return None, pos
    if code == 0x1:
        if length > 1:
            raise IonError('bool of length %d' % length)
        return length == 1, pos
    if code == 0xE and length < 3:
        raise IonError('annotation wrapper of length %d' % length)
    if length == 14 or code == 0xD and length == 1:
        # A struct whose L is 1 has its fields sorted, and at least one.
        sorted_struct = length == 1
        length, pos = _var_uint(data, pos, end)
        if sorted_struct and length == 0:
            raise IonError('sorted struct without fields')
    stop = pos + length
    if stop > end:
        raise IonError('truncated')

    if code == 0x0:
        return _PAD, stop
    if code == 0x2:
        return int.from_bytes(data[pos:stop], 'big'), stop
    if code == 0x3:
        magnitude = int.from_bytes(data[pos:stop], 'big')
        if not magnitude:
            raise IonError('negative zero')
        return -magnitude, stop
    if code == 0x4:
        if length == 0:
            return 0.0, stop
        if length == 4:
            return struct.unpack('>f', data[pos:stop])[0], stop
        if length == 8:
            return struct.unpack('>d', data[pos:stop])[0], stop
        raise IonError('float of length %d' % length)
    if code == 0x5:
        if length == 0:
            return decimal.Decimal(0), stop
        return _decimal(data, pos, stop), stop
    if code == 0x6:
        if length < 2:
            raise IonError('timestamp of length %d' % length)
        return Timestamp(data[pos:stop]), stop
    if code == 0x7:
        return Symbol(int.from_bytes(data[pos:stop], 'big')), stop
    if code == 0x8:
        try:
            return data[pos:stop].decode('utf-8'), stop
        except UnicodeDecodeError as error:
            raise IonError(str(error)) from None
    if code in (0x9, 0xA):
        return bytes(data[pos:stop]), stop

    if depth >= _MAX_DEPTH:
        raise IonError('nested too deeply')
    if code in (0xB, 0xC):
        items = []
        while pos < stop:
            item, pos = _value(data, pos, stop, depth + 1)
            if item is not _PAD:
                items.append(item)
        return (items if code == 0xB else tuple(items)), stop
    if code == 0xD:
        fields: dict[int, object] = {}
        while pos < stop:
            name, pos = _var_uint(data, pos, stop)
            item, pos = _value(data, pos, stop, depth + 1)
            # A field whose value is a pad is padding, name and all.
            if item is not _PAD:
                fields[name] = item
        return fields, stop

    # 0xE: annotations, symbol IDs that are read past, then the value.
    size, pos = _var_uint(data, pos, stop)
    annotations_end = pos + size
    if size == 0 or annotations_end >= stop:
        raise IonError('malformed annotations')
    while pos < annotations_end:
        _annotation, pos = _var_uint(data, pos, annotations_end)
    if data[pos] >> 4 == 0xE:
        raise IonError('annotation wrapper around an annotation wrapper')
    value, pos = _value(data, pos, stop, depth + 1)
    if value is _PAD:
        raise IonError('annotation wrapper around padding')
    if pos != stop:
        raise IonError('annotation wrapper longer than its value')
    return value, stop
