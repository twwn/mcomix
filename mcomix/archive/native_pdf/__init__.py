"""The native PDF handler, which runs PyMuPDF in a process of its own.

parent.py is the BaseArchive the rest of MComix sees, manager.py starts
the worker process and proxies calls to it, and child.py is what runs
there.
"""

# vim: expandtab:sw=4:ts=4
