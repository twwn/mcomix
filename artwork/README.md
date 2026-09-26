### 2023 MComix icon update (fully vectorized)

`mcomix_icon_artwork.svg` is the Inkscape source file for a 2023 update of the icon artwork, previously available only as a bitmap image (see below).

The updated icon is rendered as a 100% vector-format SVG, making it fully scalable to any size with no degradation.
The new vector artwork is a mostly-faithful recreation of the original artwork, but addresses several visual defects found in the previous rendering (when viewed at full scale).

The SVG file in this directory represents the icon "source code".
`../mcomix/images/mcomix.svg` is the new MComix icon image, exported as an optimized SVG suitable for GUI applications.

All bitmap-format icons (in various standard sizes) are generated directly from the optimized SVG file. The `Makefile` in this directory should be run after editing  `mcomix_icon_arwork.svg`. It will first generate the optimized `../mcomix/images/mcomix.svg` file, then generate all of the necessary PNG icons from the optimized SVG.

A set of icon files following the FreeDesktop icon standard are also generated into `../share/icons/hicolor/`, in both PNG and SVG format.

Updating the Windows icon file `../mcomix/images/mcomix.ico` is currently a manual process performed with the GIMP gui.

### Historical MComix icon artwork (bitmap)

The original MComix icon artwork was created by @oxaric.
It was available only as a 2655px x 1988px PNG bitmap.
The original vector sources can no longer be located.

Standard icon sizes were produced by scaling down the PNG file, with mixed results. (Smaller sizes became increasingly blurry.)

The original `mcomix-large.png` art can be retrieved via the git history.

