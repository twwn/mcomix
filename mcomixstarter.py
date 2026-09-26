#!/usr/bin/env python3

"""MComix - GTK Comic Book Viewer
"""

# -------------------------------------------------------------------------
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# -------------------------------------------------------------------------
import multiprocessing

from mcomix.__main__ import main

if __name__ == '__main__':
    # This is the script the Windows build freezes, and in a frozen build
    # the processes MComix reads PDFs in are MComix itself, started
    # again: freeze_support() is what turns such a start into the worker
    # it is meant to be, instead of a second MComix that rejects the
    # arguments it was given.  Outside a frozen build it does nothing.
    multiprocessing.freeze_support()
    main()
