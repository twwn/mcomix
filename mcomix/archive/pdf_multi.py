"""Shim module to conditionally load the FitzArchive class."""

import os
from importlib import metadata

from mcomix import log
from mcomix.archive.archive_base import BaseArchive, DisabledArchive

from mcomix.version_tools import Version

#: Lowest usable PyMuPDF release.  The first to publish wheels for the
#: oldest Python MComix supports was 1.23.5, but 1.23.5, 1.24.0 and 1.24.5
#: take the process down with a segmentation fault when their extension is
#: loaded after GTK 4, which MComix always has loaded by then; 1.24.7 was
#: the first that did not.  Keep in step with the PyMuPDF requirement in
#: pyproject.toml; test/test_pdf_multi.py checks that the two agree.
PYMUPDF_VERSION_REQUIRED = "1.24.7"


class DisabledError(RuntimeError):
    """The native handler was switched off in the environment."""


class UnsupportedFitzVersionError(ImportError):

    """PyMuPDF is installed, but too old to drive the native handler."""

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

    Logged under its own name when archive_tools passes it over, which
    says what it stands for."""

    helper = 'PyMuPDF'


def module_version(module: object) -> str:
    """Return the version of the PyMuPDF <module>, as a string.

    Note that this is the version of the binding, not of the MuPDF library
    it is built against; the two are numbered independently, and the
    library's is regularly the lower of the two.
    """
    # __version__ only exists from PyMuPDF 1.23 onward, but an install too
    # old to have it is also too old to be supported, and reporting its
    # version is the whole point of asking.
    return str(getattr(module, "__version__", None) or getattr(module, "VersionBind", "0"))


def installed_version() -> str | None:
    """Return the version of the PyMuPDF that is installed, or None.

    Read from the package's metadata, so that nothing is loaded to learn
    it: a release too old to use can crash the process on being imported.
    Only a PyMuPDF that came without its metadata - a frozen build, say -
    is imported to be asked.
    """
    try:
        return metadata.version("PyMuPDF")
    except metadata.PackageNotFoundError:
        pass
    try:
        import pymupdf
    except ImportError:
        try:
            # PyMuPDF only gained its own name in 1.24.3.  Before that it
            # was importable as "fitz" alone, a name it shares with an
            # unrelated package on PyPI.
            import fitz as pymupdf  # type: ignore[no-redef,import-untyped]
        except ImportError:
            return None
    return module_version(pymupdf)


def is_supported_version(version: str) -> bool:
    """Return whether PyMuPDF <version> can drive the native PDF handler."""
    return Version(version) >= Version(PYMUPDF_VERSION_REQUIRED)


def load_handler() -> type[BaseArchive]:
    """The class that opens PDFs natively: FitzArchive from
    native_pdf.parent where a PyMuPDF recent enough is installed, and
    DisabledFitzArchive otherwise.

    The version is settled before anything of PyMuPDF's is imported.
    """
    try:
        if os.environ.get("MCOMIX_DISABLE_PDF_MULTI") is not None:
            raise DisabledError("MCOMIX_DISABLE_PDF_MULTI set in environment")
        pymupdf_version = installed_version()
        if pymupdf_version is None:
            raise ImportError("PyMuPDF is not installed")
        if not is_supported_version(pymupdf_version):
            raise UnsupportedFitzVersionError(found_version=pymupdf_version)
        from mcomix.archive.native_pdf.parent import FitzArchive

        log.info("Native PDF handler loaded, PyMuPDF version %s", pymupdf_version)
        return FitzArchive
    except (DisabledError, ImportError) as ex:
        log.info("Can't enable pdf_multi: %s", str(ex))
        return DisabledFitzArchive


#: What opens a PDF natively, decided once, on import.
PdfMultiArchive: type[BaseArchive] = load_handler()

# vim: expandtab:sw=4:ts=4
