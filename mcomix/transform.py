""" A series of a few simple linear transforms. """

# Allow class name in annotations while still defining class
from __future__ import annotations


class Matrix:
    """Simple linear transformations represented as a 2x2 matrix.

    Note that the current implementation does not support arbitrary
    matrices. Instead, the predefined Matrix objects and conversion
    functions in the Transform class should be used to create Matrix
    objects."""

    def __init__(self, m1: float, m2: float, m3: float, m4: float) -> None:
        """Initialize a row-major transformation matrix."""
        self.m: tuple[float, float, float, float] = (m1, m2, m3, m4)

    def __str__(self) -> str:
        return str(self.m)

    def __repr__(self) -> str:
        args = ", ".join([str(x) for x in self.m])
        return f'Matrix({args})'

    def __bool__(self) -> bool:
        """Does this matrix perform any operations (is not identity)?"""
        return self != Transform.ID

    def __add__(self, other: object) -> Matrix:
        """Combine Matrices: self + other."""
        if not isinstance(other, Matrix):
            return NotImplemented
        a = self.m
        b = other.m
        return Matrix(
            b[0] * a[0] + b[1] * a[2],
            b[0] * a[1] + b[1] * a[3],
            b[2] * a[0] + b[3] * a[2],
            b[2] * a[1] + b[3] * a[3],
        )

    def __radd__(self, other: object) -> Matrix:
        """Combine Matrices: other + self."""
        if isinstance(other, Matrix):
            return other + self
        return NotImplemented

    def __eq__(self, other: object) -> bool:
        """Test equality: self == other."""
        if isinstance(other, Matrix):
            return len(self.m) == len(other.m) and all([
                self.m[i] == other.m[i]
                for i in range(len(self.m))
            ])
        return NotImplemented

    def __ne__(self, other: object) -> bool:
        """Test inequality: self != other."""
        if isinstance(other, Matrix):
            return not self == other
        return NotImplemented

    def and_then(self, next: Matrix) -> Matrix:
        """The matrix result of transforming self by 'next'."""
        return self + next

    def and_then_all(self, *nexts: Matrix) -> Matrix:
        """The matrix resulting from self transformed by each 'nexts' in turn."""
        out = self
        for m in nexts:
            out += m
        return out

    def swaps_axes(self) -> bool:
        """ Determines whether this matrix includes a transpose of the axes. """
        return self.m[0] == 0

    def rotated(self, deg: int) -> Matrix:
        """The matrix result of rotating self by 'deg' degrees."""
        return self + Transform.from_rotation(deg)

    def scaled(self, s0: float, s1: float | None = None) -> Matrix:
        """The matrix result of scaling self by the provided factor(s).

        t.scale(s) will scale both dimensions by s.
        t.scale(s0, s1) will scale x by s0, and y by s1."""
        if s1 is None:
            s1 = s0
        return self + Transform.from_scales(s0, s1)

    def flipped(self, x: bool = False, y: bool = False) -> Matrix:
        """The matrix result of applying the specified flips."""
        if x and y:
            return self + Transform.ROT180
        if x:
            return self + Transform.INVX
        if y:
            return self + Transform.INVY
        return self

    def flipped_x(self) -> Matrix:
        """The matrix result of flipping self horizontally."""
        return self.flipped(x=True)

    def flipped_y(self) -> Matrix:
        """The matrix result of flipping self vertically."""
        return self.flipped(y=True)

    def to_image_transforms(self) -> tuple[tuple[float, float], int, tuple[bool, bool]]:
        """ Decomposes the transform to a sequence of hints to basic transform
        instructions typically found in image processing libraries. The sequence
        will refer to the positive scaling factors to be applied for each axis
        first, followed by at most one rotation, and finally followed by at most
        one flip.
        @return a tuple (s, r, f) where s is a sequence of positive scaling
        factors for the corresponding axes, r is one of (0, 90, 180, 270),
        referring to the clockwise rotation to be applied, and f is a sequence
        of bools where True refers to the corresponding axis to be flipped. """
        # The scales belong to the axes as they were before the
        # rotation, since that is the order the sequence puts them in
        # and the order from_image_transforms() rebuilds them in.  Read
        # straight off the rows, they came out the other way round for
        # every transform that swaps the axes.
        if self.swaps_axes():
            s: tuple[float, float] = (abs(self.m[2] + self.m[3]),
                                      abs(self.m[0] + self.m[1]))
        else:
            s = (abs(self.m[0] + self.m[1]), abs(self.m[2] + self.m[3]))
        r: int = 90 if self.swaps_axes() else 0
        f: tuple[bool, bool] = (
            self.swaps_axes() ^ (self.m[0] < 0 or self.m[1] < 0),
            (self.m[2] < 0 or self.m[3] < 0)
        )
        if all(f):
            f = (False, False)
            r += 180
        if f[0] and r == 90:
            # Try to avoid horizontal flips because they tend to be slow, given
            # a certain combination of hardware, memory layout and libraries.
            f = (False, True)
            r = 270
        return (s, r, f)


class Transform(Matrix):

    ID = Matrix(1, 0, 0, 1)
    ROT90 = Matrix(0, -1, 1, 0)
    ROT180 = Matrix(-1, 0, 0, -1)
    ROT270 = Matrix(0, 1, -1, 0)
    INVX = Matrix(-1, 0, 0, 1)
    INVY = Matrix(1, 0, 0, -1)
    TRP = Matrix(0, 1, 1, 0)
    TRPINV = Matrix(0, -1, -1, 0)

    @classmethod
    def __call__(cls, *values: float) -> Matrix:
        """Construct a new Matrix by calling Transform(values)."""
        return Matrix(*values)

    @classmethod
    def from_rotation(cls, deg: int) -> Matrix:
        """Get the predefined Matrix for a supported rotation."""
        if abs(deg) not in (0, 90, 180, 270):
            raise ValueError("illegal rotation angle: " + str(deg))
        if deg < 0: deg = 360 + deg
        if deg == 90:
            return cls.ROT90
        if deg == 180:
            return cls.ROT180
        if deg == 270:
            return cls.ROT270
        return cls.ID

    @classmethod
    def from_scales(cls, s0: float, s1: float) -> Matrix:
        """Get a Matrix representing the given x and y scales."""
        if s0 == 0 or s1 == 0:
            raise ValueError("illegal scaling factor(s): " + str((s0, s1)))
        return Matrix(s0, 0, 0, s1)

    @classmethod
    def from_flips(cls, x: bool, y: bool) -> Matrix:
        """Get the predefined Matrix representing the given x and y flips."""
        if x and y:
            return cls.ROT180
        if x:
            return cls.INVX
        if y:
            return cls.INVY
        return cls.ID

    @classmethod
    def from_image_transforms(
            cls,
            t: tuple[tuple[float, float], int, tuple[bool, bool]]
    ) -> Matrix:
        """Create a Matrix transform from a set of image transforms."""
        s, r, f = t[0:3]
        return (
            cls.from_scales(*s)
            + cls.from_rotation(r)
            + cls.from_flips(*f)
        )

# vim: expandtab:sw=4:ts=4
