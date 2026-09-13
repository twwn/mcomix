"""The archive handlers, one module per format.

Every one of them is a BaseArchive: it lists the files it holds by
name and writes any of them out on demand, so that the rest of MComix
reads a book without knowing what it is packed in.  A handler is
chosen by archive_tools.get_archive_handler(), which asks each in turn
whether it is available - several need a program or a module that may
not be installed.
"""

# vim: expandtab:sw=4:ts=4
