"""jpeg_turn.py - Turning a JPEG picture without encoding it again.

A JPEG picture turned by decoding it and encoding the turned pixels
loses detail every time.  There are two ways round that.  jpegtran,
from libjpeg-turbo, turns the compressed blocks themselves, which loses
nothing; but only where the picture's width or height, whichever the
turn moves to the other side, is a whole number of blocks, 8 or 16
pixels, since a part block cannot change sides.  Otherwise, and where
jpegtran is not installed, the turn is written as the picture's Exif
orientation tag, which leaves the pixels alone and which every common
viewer follows.
"""

import contextlib
import struct
import subprocess
from collections.abc import Iterator

from PIL import Image

from mcomix import process

#: The Exif orientation tag.
ORIENTATION = 0x0112

#: Each Exif orientation as the turn it shows the stored picture with:
#: mirrored left to right first or not, then turned clockwise by so
#: many degrees.
_TURNS = {1: (False, 0), 2: (True, 0), 3: (False, 180), 4: (True, 180),
          5: (True, 270), 6: (False, 90), 7: (True, 90), 8: (False, 270)}
_ORIENTATIONS = {turn: orientation for orientation, turn in _TURNS.items()}

#: The jpegtran option that makes each turn of the pixels.
_JPEGTRAN = {(False, 90): ['-rotate', '90'], (False, 180): ['-rotate', '180'],
             (False, 270): ['-rotate', '270'],
             (True, 0): ['-flip', 'horizontal'],
             (True, 180): ['-flip', 'vertical'],
             (True, 90): ['-transverse'], (True, 270): ['-transpose']}

_SOI = b'\xff\xd8'
_EXIF = b'Exif\x00\x00'


class NotLossless(ValueError):
    """The turn cannot be written without changing the pixels or
    without the reader having MComix follow the Exif orientation."""


def orientation_of(data: bytes) -> int:
    """The Exif orientation of the JPEG picture <data>, 1 where it has
    none or one that means nothing.

    Read from the Exif block itself, as Pillow reads a JPEG's, the
    first one: opening the picture with Pillow refuses one of more
    pixels than its limit (Image.MAX_IMAGE_PIXELS) with an error of its
    own, though the turn needs none of them.
    """
    for marker, start, end in _segments(data):
        if marker == 0xe1 and data[start + 4:start + 10] == _EXIF:
            exif = Image.Exif()
            with _damaged_exif():
                exif.load(data[start + 10:end])
                orientation = exif.get(ORIENTATION, 1)
            return orientation if orientation in _TURNS else 1
    return 1


@contextlib.contextmanager
def _damaged_exif() -> Iterator[None]:
    """Raise ValueError for what Pillow raises over a damaged Exif
    block, which the caller says the picture cannot be turned for.

    Pillow parses and writes Exif with struct and its own TIFF code,
    and a damaged block raises whatever those meet: SyntaxError for a
    TIFF header that is not one, struct.error or TypeError for an entry
    of the wrong type, among others.
    """
    try:
        yield
    except (OSError, ValueError):
        raise
    except Exception as error:
        raise ValueError(f'damaged Exif block: {error}') from error


def turned(orientation: int, degrees: int) -> int:
    """The Exif orientation that shows what <orientation> shows turned
    a further <degrees> clockwise."""
    mirrored, turn = _TURNS[orientation]
    return _ORIENTATIONS[(mirrored, (turn + degrees) % 360)]


def _segments(data: bytes) -> "list[tuple[int, int, int]]":
    """The marker, start and end of each segment of the JPEG picture
    <data> up to its first scan, the start being that of its marker."""
    if not data.startswith(_SOI):
        raise ValueError('not a JPEG picture')
    found = []
    start = len(_SOI)
    while True:
        if data[start:start + 1] != b'\xff' or start + 4 > len(data):
            raise ValueError('damaged JPEG picture')
        marker = data[start + 1]
        if marker == 0xff:
            # Fill bytes may stand before a marker.
            start += 1
            continue
        length, = struct.unpack('>H', data[start + 2:start + 4])
        end = start + 2 + length
        found.append((marker, start, end))
        if marker == 0xda:
            return found
        start = end


def with_orientation(data: bytes, orientation: int) -> bytes:
    """The JPEG picture <data> with <orientation> for its Exif
    orientation, and nothing else changed."""
    segments = _segments(data)
    for marker, start, end in segments:
        if marker == 0xe1 and data[start + 4:start + 10] == _EXIF:
            tiff = start + 10
            changed = _set_in_place(data, tiff, end, orientation)
            if changed is not None:
                return changed
            # No tag to change: write the block anew with one.
            exif = Image.Exif()
            with _damaged_exif():
                exif.load(data[tiff:end])
            return _with_exif(data, start, end, exif, orientation)
    # None at all: a new block, after the JFIF one that has to come
    # first, where there is one.
    after = segments[0][2] if segments[0][0] == 0xe0 else len(_SOI)
    return _with_exif(data, after, after, Image.Exif(), orientation)


def _set_in_place(data: bytes, tiff: int, end: int,
                  orientation: int) -> "bytes | None":
    """<data> with the orientation entry of the first directory of the
    Exif block whose TIFF header starts at <tiff> set to <orientation>,
    or None where that directory has no such entry."""
    order = {b'II': '<', b'MM': '>'}.get(data[tiff:tiff + 2])
    if order is None:
        raise ValueError('damaged Exif block')
    first, = struct.unpack(order + 'I', data[tiff + 4:tiff + 8])
    directory = tiff + first
    if directory + 2 > end:
        raise ValueError('damaged Exif block')
    count, = struct.unpack(order + 'H', data[directory:directory + 2])
    for entry in range(directory + 2, min(directory + 2 + 12 * count, end - 11), 12):
        tag, kind, values = struct.unpack(order + 'HHI', data[entry:entry + 8])
        if tag == ORIENTATION and kind == 3 and values == 1:
            return (data[:entry + 8] + struct.pack(order + 'H', orientation)
                    + data[entry + 10:])
    return None


def _with_exif(data: bytes, start: int, end: int, exif: Image.Exif,
               orientation: int) -> bytes:
    """<data> with the part from <start> to <end> replaced by an Exif
    block of <exif> whose orientation is <orientation>."""
    exif[ORIENTATION] = orientation
    with _damaged_exif():
        payload = exif.tobytes()
    if not payload.startswith(_EXIF):
        payload = _EXIF + payload
    if len(payload) + 2 > 0xffff:
        raise ValueError('Exif block too large')
    block = b'\xff\xe1' + struct.pack('>H', len(payload) + 2) + payload
    return data[:start] + block + data[end:]


def _jpegtran() -> "str | None":
    return process.find_executable(('jpegtran',))


def _turn_pixels(data: bytes, mirrored: bool, degrees: int) -> "bytes | None":
    """<data> with its pixels turned, mirrored first if <mirrored>, then
    <degrees> clockwise, by jpegtran, or None where jpegtran is not
    installed or the picture is not a whole number of blocks the way
    the turn needs."""
    exe = _jpegtran()
    if exe is None:
        return None
    command = [exe, '-copy', 'all', '-perfect', *_JPEGTRAN[mirrored, degrees]]
    try:
        done = subprocess.run(command, input=data, capture_output=True,
                              timeout=60,
                              creationflags=process.CREATIONFLAGS)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0 or not done.stdout.startswith(_SOI):
        return None
    return done.stdout


def turn(data: bytes, degrees: int, follow_exif: bool) -> bytes:
    """The JPEG picture <data> turned <degrees> further clockwise than
    it is shown, without encoding its pixels again.

    <follow_exif> says whether the picture is shown as its Exif
    orientation says, as MComix shows it while "auto rotate from exif"
    is set; where it is not, the orientation it has is what the reader
    has never seen, and the turn starts from the stored pixels.  The
    pixels are turned where jpegtran can; otherwise the turn is the
    orientation tag's, which only a reader who follows it sees: there
    NotLossless is raised for one who does not.
    """
    start = orientation_of(data) if follow_exif else 1
    mirrored, degrees = _TURNS[turned(start, degrees)]
    if (mirrored, degrees) == (False, 0):
        return with_orientation(data, 1) if start != 1 else data
    pixels = _turn_pixels(data, mirrored, degrees)
    if pixels is not None:
        # jpegtran keeps the tag it was given, which was already
        # counted in.
        return with_orientation(pixels, 1)
    if not follow_exif:
        raise NotLossless()
    return with_orientation(data, _ORIENTATIONS[mirrored, degrees])


def is_jpeg(path: str) -> bool:
    """Whether the file at <path> is a JPEG picture, by its first bytes."""
    with open(path, 'rb') as file:
        return file.read(3) == _SOI + b'\xff'
