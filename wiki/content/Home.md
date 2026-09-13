MComix
===

Summary
---

MComix is a user-friendly, customizable image viewer. It is specifically designed to handle comic books (both Western comics and manga) and supports a variety of container formats (including CBR, CBZ, CB7, CBT, LHA and PDF). It is written in Python using GTK through the PyGGObject bindings, and runs on both Linux and Windows.

MComix is a fork of the [Comix project](http://comix.sourceforge.net/), and aims to add bug fixes and stability improvements after Comix development came to a halt in late 2009.

[[download_button]]
<br />
[[project_screenshots]]

<a name="Dependencies"></a>Dependencies
---

The following programs and libraries are required in order to install and run MComix:

- [Python 3.7](http://www.python.org/) or newer.
- [GTK 4](http://www.gtk.org/), [PyGObject](https://pygobject.readthedocs.io/en/latest/) 3.36.0 or newer, and [PyCairo](https://github.com/pygobject/pycairo) 1.16.0 or newer. Windows users need to install [MSYS2](https://www.msys2.org/) and install the necessary packages there.
- [Python Imaging Library Fork (Pillow)](https://pypi.python.org/pypi/Pillow) 6.0.0 or newer.

[libadwaita](https://gnome.pages.gitlab.gnome.org/libadwaita/) is optional. Its stylesheet is the only one that reads the colours a GTK 4 desktop theme states, so MComix follows the desktop's theme throughout where it is installed, and as far as plain GTK 4 can be told where it is not.

The above packages are only required if you intend to run MComix from source or on UNIX-like systems. The pre-built Windows packages already include all dependencies.

In order to to read RAR/CBR archives, either `rar` or `unrar` has to be installed. Alternatively, MComix can also make use of [UnRAR64.dll/libunrar.so](http://www.rarsoft.com/rar_add.htm). The library should be placed either in your default system library directory, or directly in MComix' root directory. To open 7Zip archives, the `7z` executable is required. Likewise, LZA/LHA archives require the `lha` executable (with fallback to `7z`). Opening PDF files requires either the [PyMuPDF](https://pypi.org/project/PyMuPDF/) package, or `mutool`, which is provided by the [MuPDF](https://mupdf.com/) software.

User manual
---

As of now, the user manual is a work-in-progress. It can be found on the [Documentation] page.

Credits
---

Comix has originally been developed by [Pontus Ekberg](http://sourceforge.net/users/herrekberg), who unfortunately disappeared from the internet one day. Many thanks to him and everyone else who contributed translations, suggestions, bug reports and fixes to this project!

Icons with a filename starting with "gimp" are taken from The GIMP, and icons with a filename starting with "tango" are taken from the Tango Desktop Project. Most other icons are made by Victor Castillejo, creator of the GNOME-Colors icon theme.

Developer resources
---

* The [Maintenance] page has instructions for common tasks related to releasing new versions of MComix.
