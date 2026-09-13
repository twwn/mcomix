# -*- coding: utf-8 -*-

"""Shim module to conditionally load the FitzArchive class."""

import os

from mcomix import log
from mcomix.archive.archive_base import BaseArchive, DisabledArchive

from mcomix.version_tools import Version

#: Lowest usable PyMuPDF release: the first one publishing wheels for the
#: oldest Python MComix supports.  Keep in step with the PyMuPDF requirement
#: in pyproject.toml; test/test_pdf_multi.py checks that the two agree.
PYMUPDF_VERSION_REQUIRED = "1.23.5"


class DisabledError(RuntimeError): pass

class UnsupportedFitzVersionError(ImportError):
    def __init__(
            self, message: str | None = None, name: str | None = None,
            path: str | None = None, found_version: str | None = None) -> None:
        self.found_version = found_version
        self.minimum_version = PYMUPDF_VERSION_REQUIRED
        if message is None:
            message = f"PyMuPDF {self.minimum_version} or later required"
            if self.found_version is not None:
                message += f", {self.found_version} found"
        super().__init__(message, name=name, path=path)


class DisabledFitzArchive(DisabledArchive):
    """Subclass of DisabledArchive used when FitzArchive is unavailable.

    This class will masquerade as FitzArchive for purposes of upstream
    reporting, so that the correct class is logged as being unavailable."""

    __name__ = "FitzArchive"


def installed_version(module: object) -> str:
    """Return the version of the PyMuPDF <module>, as a string.

    Note that this is the version of the binding, not of the MuPDF library
    it is built against; the two are numbered independently, and the
    library's is regularly the lower of the two.
    """
    # __version__ only exists from PyMuPDF 1.23 onward, but an install too
    # old to have it is also too old to be supported, and reporting its
    # version is the whole point of asking.
    return str(getattr(module, "__version__", None) or getattr(module, "VersionBind", "0"))


def is_supported_version(version: str) -> bool:
    """Return whether PyMuPDF <version> can drive the native PDF handler."""
    return Version(version) >= Version(PYMUPDF_VERSION_REQUIRED)


# On import, this code tests for a compatible version of the PyMuPDF
# module, and exports as "PdfMultiArchive" either the FitzArchive class
# from native_pdf.parent, or the DisabledFitzArchive class (aliased to
# 'FitzArchive' for caller-side reporting purposes)

try:
    if os.environ.get("MCOMIX_DISABLE_PDF_MULTI") is not None:
        raise DisabledError("MCOMIX_DISABLE_PDF_MULTI set in environment")
    try:
        import pymupdf
    except ImportError:
        # PyMuPDF only gained its own name in 1.24.3.  Before that it was
        # importable as "fitz" alone, a name it shares with an unrelated
        # package on PyPI.
        import fitz as pymupdf  # type: ignore[no-redef,import-untyped]

    pymupdf_version = installed_version(pymupdf)
    if not is_supported_version(pymupdf_version):
        raise UnsupportedFitzVersionError(found_version=pymupdf_version)
    from mcomix.archive.native_pdf.parent import FitzArchive

    log.info("Native PDF handler loaded, PyMuPDF version %s", pymupdf_version)
    PdfMultiArchive: type[BaseArchive] = FitzArchive
except (DisabledError, ImportError) as ex:
    log.info("Can't enable pdf_multi: %s", str(ex))
    PdfMultiArchive = DisabledFitzArchive

# vim: expandtab:sw=4:ts=4
