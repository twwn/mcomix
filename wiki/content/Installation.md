# Installation instructions

[TOC]

## Installation on Linux
MComix is available in most major distributions' packaging systems, and should be installed using the distribution's system mechanism if possible. If your distribution only ships an ancient version of MComix, you might opt to install it as Flatpak instead.

### Ubuntu / Debian
Ubuntu has packaged an up-to-date version of MComix starting with Ubuntu 23.04 (Lunar). The same holds true for Debian 12 (Bookworm).

    :::bash
    ~ $ sudo apt install mcomix

### openSUSE
openSUSE users can download a current MComix version starting from openSUSE 15.4 (Leap)

    :::bash
    ~ $ sudo zypper install mcomix

### Arch Linux
The Arch Linux User Repository (AUR) usually has the most current version of MComix.

    :::bash
    ~ $ yay -S mcomix

### Flathub

If your distribution supports the installation of [Flatpaks](https://flatpak.org/setup/), you can download and install MComix from Flathub:

    :::bash
    ~ $ flatpak install flathub net.sourceforge.mcomix

## Installation on Windows

### Winget
Starting with version 3.0.0, MComix is available from the [WinGet package manager](https://learn.microsoft.com/en-us/windows/package-manager/winget/).

    :::powershell
    PS > winget install mcomix

### Chocolatey
Users of the [Chocolatey package manager](https://chocolatey.org/install) can download the `mcomix` package, which takes care of installation and upgrading MComix.

    :::powershell
    PS > choco install -y mcomix

### Scoop
MComix is also available in the Extras bucket of the [Scoop package manager](https://scoop.sh/). Follow the following steps in a console:

    :::bash
    > scoop bucket add extras
    > scoop install extras/mcomix

### Manual installation
Simply install the MSI package. The installation requires administrator access. If such access is not available on the machine you plan to use MComix on, you can fall back extracting `mcomix-win64-<version>.zip` anywhere on your harddisk, and run `MComix.exe` from there.

The uninstaller leaves user data, such as the configuration and library contents, on your disk. To completely remove these files, manually delete the folder `%APPDATA%/MComix`.

# Running MComix from source
Since MComix has heavy dependencies on non-Python binary packages that are tendious to install, running it from source is somewhat difficult. At the very least, you will need PyGObject, which has a very good [Getting Started guide](https://pygobject.readthedocs.io/en/latest/getting_started.html) for various operating systems. MComix requires *GTK 4*, which is the version that guide installs, so its package manager calls can be followed as they are written.

_Windows/MSYS2 note_: Due to a bug in Setuptools, the ujson package, which is needed to process pyproject.toml projects, cannot be built on MSYS2. Please install the `mingw-w64-x86_64-python-ujson` package from Pacman.

With PyGObject installed, you can now create a virtual environment for MComix. Virtual environments used in Python to separate dependencies of various Python applications from each other, in order to avoid depdency conflicts between system and application packages. Virtual environments can be created in a variety of ways using different packages, but the most simple is probably using the `venv` package, which is often bundled with Python.

    :::bash
    ~ $ python3 -m venv --system-site-packages mcomix-venv
    ~ $ source mcomix-venv/bin/activate
    (mcomix-venv) ~ $

Using the `--system-site-packages` switch is important to give the environment access to system packages. Without it, you will be missing the pre-built PyGObject library, and Python will attempt to build it from source, which will likely fail unless you installed a lot of additional dependencies. When the virtual environment has been activated by sourcing the activation script, all calls to `python`, `pip` and similar Python tools will now refer to your virtual environment instead of the system environment. This means that you can easily install packages even without elevated rights, and uninstall them quickly by deleting the virtual environment directory. Instead of first activating the virtual environment in the shell, it is also possible to call `mcomix-venv/bin/python` directly.

With the virtual environment activated, extract the MComix source tarball and install the package using the `pip` standard module:

    :::bash
    (mcomix-venv) ~ $ tar -xzf mcomix-<versionnr>.tar.gz
    (mcomix-venv) ~ $ cd mcomix-<versionnr>
    (mcomix-venv) mcomix-<versionnr> $ python -m pip install .

Pip now installs all required dependencies as well as the `mcomix` executable. When the virtual environment is active, calling `mcomix` will now run the program. You can also run `mcomix-venv/bin/mcomix` directly without activating the virtual environment.

If you want additional file format support for MComix, install the optional depdency `fileformats`:

    :::bash
    (mcomix-venv) mcomix-<versionnr> $ python -m pip install .[fileformats]

On Linux, you may want to copy additional application meta files to `/usr/local/share/` for better desktop integration. All files are stored in the `share` folder in the MComix source archive, with paths already matching their expected destination in `/usr/local/share`. Please note that these files cannot be automatically uninstalled when copied by hand.

The extracted MComix directory can now be safely deleted. To uninstall MComix, simply delete the virtual environment folder, and MComix' settings directory. It can be found in your user directory, usually `~/.config/mcomix` on Linux and `%APPDATA%/MComix` on Windows.

# Developing MComix

You can mostly follow the regular instructions above. Instead of using a source tarball, check out the repository from SourceForge with Git. Then, in the repository folder, install an editable package of MComix by passing the `-e` switch to `pip install`. This will still download all dependencies, but instead of copying a read-only package to your virtual environment, the package will be linked to the repository source code. This way, you can modify the source code, and changes will appear immediately after restarting MComix.

    :::bash
    (mcomix-venv) mcomix $ python -m pip install -e .[dev]

The `dev` optional depdency installs tools for static code analysis, Python language server and other useful tools.
