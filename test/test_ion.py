"""The binary Ion reader, against the examples of Amazon's specification
and against values written here.

dumps() below writes binary Ion for the tests: MComix only ever reads
it, so the writer is the tests' own.  test_kfx.py builds its books with
it.
"""

import decimal
import random
import struct
import unittest

from mcomix.archive import ion
from mcomix.archive.ion import IonError, Symbol


class Annotated:
    """<value>, annotated with the symbol IDs <annotations>, for dumps()."""

    def __init__(self, annotations, value):
        self.annotations = annotations
        self.value = value


def var_uint(value):
    """<value> as a VarUInt."""
    octets = [0x80 | value & 0x7F]
    value >>= 7
    while value:
        octets.insert(0, value & 0x7F)
        value >>= 7
    return bytes(octets)


def _typed(code, representation):
    """A value of type <code> whose representation is <representation>."""
    if len(representation) < 14:
        return bytes([code << 4 | len(representation)]) + representation
    return bytes([code << 4 | 14]) + var_uint(len(representation)) + representation


def _magnitude(value):
    """The non-negative <value> as a UInt, in as few octets as it takes."""
    return value.to_bytes((value.bit_length() + 7) // 8, 'big')


def _encode(value):
    """<value> as a binary Ion value, without the version marker."""
    if value is None:
        return b'\x0f'
    if isinstance(value, bool):
        return b'\x11' if value else b'\x10'
    if isinstance(value, Symbol):
        return _typed(0x7, _magnitude(value))
    if isinstance(value, int):
        return _typed(0x2 if value >= 0 else 0x3, _magnitude(abs(value)))
    if isinstance(value, float):
        return _typed(0x4, struct.pack('>d', value))
    if isinstance(value, decimal.Decimal):
        sign, digits, exponent = value.as_tuple()
        coefficient = int(''.join(map(str, digits)))
        magnitude = coefficient.to_bytes(coefficient.bit_length() // 8 + 1, 'big')
        if sign:
            magnitude = bytes([magnitude[0] | 0x80]) + magnitude[1:]
        return _typed(0x5, _var_int(exponent) + magnitude)
    if isinstance(value, str):
        return _typed(0x8, value.encode('utf-8'))
    if isinstance(value, bytes):
        return _typed(0xA, value)
    if isinstance(value, list):
        return _typed(0xB, b''.join(map(_encode, value)))
    if isinstance(value, tuple):
        return _typed(0xC, b''.join(map(_encode, value)))
    if isinstance(value, dict):
        return _typed(0xD, b''.join(var_uint(name) + _encode(field)
                                    for name, field in value.items()))
    if isinstance(value, Annotated):
        annotations = b''.join(map(var_uint, value.annotations))
        return _typed(0xE, var_uint(len(annotations)) + annotations
                      + _encode(value.value))
    raise TypeError(value)


def _var_int(value):
    """<value> as a VarInt."""
    magnitude = abs(value)
    octets = [magnitude & 0x7F]
    magnitude >>= 7
    while magnitude:
        octets.insert(0, magnitude & 0x7F)
        magnitude >>= 7
    if octets[0] & 0x40:
        octets.insert(0, 0)
    if value < 0:
        octets[0] |= 0x40
    octets[-1] |= 0x80
    return bytes(octets)


def dumps(value):
    """<value> as a binary Ion stream holding it alone."""
    return ion.VERSION_MARKER + _encode(value)


def _stream(hexadecimal):
    """The binary Ion stream holding the value written as <hexadecimal>."""
    return ion.VERSION_MARKER + bytes.fromhex(hexadecimal)


class IonTest(unittest.TestCase):

    def test_scalars(self):
        """Each type read from the bytes the specification gives it."""
        for hexadecimal, expected in (
                ('0f', None), ('2f', None), ('df', None),
                ('10', False), ('11', True),
                ('20', 0), ('21 7f', 127), ('22 01 00', 256), ('31 05', -5),
                ('40', 0.0), ('44 3f 80 00 00', 1.0),
                ('48 c0 00 00 00 00 00 00 00', -2.0),
                ('50', decimal.Decimal(0)),
                # 0.25: exponent -2, coefficient 25; -1.5: -1, -15.
                ('52 c2 19', decimal.Decimal('0.25')),
                ('52 c1 8f', decimal.Decimal('-1.5')),
                ('70', Symbol(0)), ('71 04', Symbol(4)),
                ('72 01 5f', Symbol(351)),
                ('83 61 62 63', 'abc'), ('80', ''),
                ('a2 ff 00', b'\xff\x00'), ('92 41 42', b'AB'),
        ):
            with self.subTest(hexadecimal):
                value = ion.loads(_stream(hexadecimal))
                self.assertEqual(value, expected)
                self.assertIs(type(value), type(expected))

    def test_timestamp(self):
        """A timestamp is kept as its representation, which is checked
        only for the two fields every one has."""
        value = ion.loads(_stream('68 80 0f d0 81 81 80 80 80'))
        self.assertIsInstance(value, ion.Timestamp)
        self.assertEqual(value, bytes.fromhex('80 0f d0 81 81 80 80 80'))
        for illegal in ('60', '61 80'):
            with self.subTest(illegal), self.assertRaises(IonError):
                ion.loads(_stream(illegal))

    def test_long_lengths(self):
        """A representation of 14 octets or more has its length in a
        VarUInt after the type descriptor."""
        text = 'x' * 200
        self.assertEqual(ion.loads(_stream('8e 01 c8') + text.encode()), text)
        self.assertEqual(ion.loads(dumps(text)), text)

    def test_containers(self):
        """A list, an S-expression and a struct, the struct's fields
        named by symbol ID."""
        self.assertEqual(ion.loads(_stream('b3 21 01 11')), [1, True])
        self.assertEqual(ion.loads(_stream('c2 71 0a')), (Symbol(10),))
        self.assertEqual(ion.loads(_stream('d3 84 21 07')), {4: 7})
        self.assertEqual(ion.loads(_stream('d0')), {})
        self.assertEqual(ion.loads(_stream('b0')), [])

    def test_sorted_struct(self):
        """A struct whose L is 1 has its length in a VarUInt, and at
        least one field."""
        self.assertEqual(ion.loads(_stream('d1 86 84 21 01 85 21 02')),
                         {4: 1, 5: 2})
        with self.assertRaises(IonError):
            ion.loads(_stream('d1 80'))

    def test_padding(self):
        """A NOP pad is passed over wherever a value could be, and a
        struct field whose value is one is padding, name and all; the
        examples are the specification's."""
        self.assertEqual(ion.loads(_stream('00 21 01 01 fe')), 1)
        self.assertEqual(
            ion.loads(_stream('0e 8e' + ' 00' * 14 + ' 11')), True)
        self.assertEqual(ion.loads(_stream('b4 00 21 05 00')), [5])
        self.assertEqual(ion.loads(_stream('d3 80 01 ac')), {})
        self.assertEqual(ion.loads(_stream('d7 84 81 61 80 02 01 02')),
                         {4: 'a'})
        self.assertEqual(ion.loads(_stream('d2 8f 00')), {})

    def test_annotations(self):
        """Annotations are read past to the value they annotate."""
        self.assertEqual(ion.loads(_stream('e3 81 83 d0')), {})
        self.assertEqual(ion.loads(_stream('e5 82 84 85 21 07')), 7)
        self.assertEqual(
            ion.loads(dumps(Annotated([3, 600], {7: ['a']}))), {7: ['a']})

    def test_illegal(self):
        """What the specification calls illegal, and what is cut off,
        is refused."""
        for hexadecimal in (
                # Bool with L from 2 to 14, negative zero, a float that
                # is neither 4 nor 8 octets, type 0xF.
                '12', '1e', '30', '31 00', '42 00 00', 'f0', 'ff',
                # Annotation wrappers: null, too short, around a pad,
                # around another wrapper, longer than their value.
                'ef', 'e1 81', 'b4 e3 81 84 00', 'e6 81 84 e3 81 84 20',
                'e4 81 84 20 20',
                # Lengths past the end, a VarUInt never terminated.
                '82 61', 'b3 21 01', 'd2 84', '8e 01',
                # Text that is not UTF-8.
                '81 ff',
        ):
            with self.subTest(hexadecimal), self.assertRaises(IonError):
                ion.loads(_stream(hexadecimal))

    def test_one_value(self):
        """A stream holds exactly one value: none, two, or no version
        marker at all is refused.  Another version marker between the
        value and the end is no value."""
        for data in (ion.VERSION_MARKER, _stream('21 01 21 02'),
                     bytes.fromhex('21 01'), b'', _stream('00')):
            with self.subTest(data), self.assertRaises(IonError):
                ion.loads(data)
        self.assertEqual(ion.loads(_stream('21 01') + ion.VERSION_MARKER), 1)

    def test_nesting(self):
        """Lists nested deeper than the reader goes are refused rather
        than taken as deep as Python's stack."""
        value = 1
        for _ in range(100):
            value = [value]
        self.assertEqual(ion.loads(dumps(value)), value)
        with self.assertRaises(IonError):
            ion.loads(dumps([value]))

    def test_round_trip(self):
        """Values written by dumps() are read back as they were."""
        generator = random.Random(50)

        def scalar():
            return generator.choice((
                None, True, False,
                generator.randint(-2 ** 70, 2 ** 70),
                generator.uniform(-1e6, 1e6),
                decimal.Decimal(generator.randint(-10 ** 12, 10 ** 12)).scaleb(
                    generator.randint(-20, 20)),
                Symbol(generator.randint(0, 100000)),
                ''.join(chr(generator.randint(32, 0x2FFF))
                        for _ in range(generator.randint(0, 30))),
                bytes(generator.randint(0, 255)
                      for _ in range(generator.randint(0, 30))),
            ))

        def value(depth):
            kind = generator.randint(0, 5 if depth < 4 else 2)
            if kind <= 2:
                return scalar()
            items = [value(depth + 1) for _ in range(generator.randint(0, 5))]
            if kind == 3:
                return items
            if kind == 4:
                return tuple(items)
            return {generator.randint(0, 2000): item for item in items}

        for _ in range(500):
            expected = value(0)
            self.assertEqual(ion.loads(dumps(expected)), expected)
            self.assertEqual(
                ion.loads(dumps(Annotated([3], expected))), expected)

    def test_writer(self):
        """The VarUInt and VarInt the tests write are the
        specification's."""
        self.assertEqual(var_uint(0), b'\x80')
        self.assertEqual(var_uint(410), b'\x03\x9a')
        self.assertEqual(_var_int(-2), b'\xc2')
        self.assertEqual(_var_int(64), b'\x00\xc0')
        self.assertEqual(_var_int(-64), b'\x40\xc0')
