# -*- coding: utf-8 -*-

"""Shim module to conditionally load the FitzArchive class."""

import os
from typing import Type

from mcomix import log
from mcomix.archive.archive_base import BaseArchive, DisabledArchive

from mcomix.version_tools import Version

FITZ_VERSION_REQUIRED = "1.19.2"


class DisabledError(RuntimeError): pass

class UnsupportedFitzVersionError(ImportError):
    def __init__(
            self, message=None, name=None, path=None,
            found_version=None):
        self.found_version = found_version
        self.minimum_version = FITZ_VERSION_REQUIRED
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


# On import, this code tests for a compatible version of the fitz
# module (PyMuPDF), and exports as "PdfMultiArchive" either the
# FitzArchive class from native_pdf.parent, or the DisabledFitzArchive
# class (aliased to 'FitzArchive' for caller-side reporting purposes)

try:
    if os.environ.get("MCOMIX_DISABLE_PDF_MULTI") is not None:
        raise DisabledError("MCOMIX_DISABLE_PDF_MULTI set in environment")
    try:
        import fitz
    except ImportError:
        import fitz_old as fitz

    fitz_version = Version(fitz.VersionFitz)
    required_version = Version(FITZ_VERSION_REQUIRED)

    if fitz_version < required_version:
        raise UnsupportedFitzVersionError(found_version=fitz.VersionFitz)
    from mcomix.archive.native_pdf.parent import FitzArchive

    log.info("Native PDF handler loaded, PyMuPDF version %s", fitz.VersionFitz)
    PdfMultiArchive: Type[BaseArchive] = FitzArchive
except (DisabledError, ImportError) as ex:
    log.info("Can't enable pdf_multi: %s", str(ex))
    PdfMultiArchive = DisabledFitzArchive

# vim: expandtab:sw=4:ts=4
