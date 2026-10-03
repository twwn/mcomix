# Icon artwork

`mcomix_icon_artwork.svg` is the icon's source, drawn in Inkscape in 2023.
It redraws the original bitmap icon as vectors, and fixes flaws that showed at full size.

## Regenerating the icons

After editing the source, run `make` here, with Inkscape on the `PATH`.
It writes, from the source:

- `../mcomix/images/icons/hicolor/scalable/apps/mcomix.svg`, the icon as plain SVG, and `<size>x<size>/apps/mcomix.png` beside it: the window's icon, which MComix finds there whether or not it is installed;
- `../mcomix/images/mcomix.png`, 212 pixels wide, which the About dialog shows;
- `../share/icons/hicolor/<size>x<size>/apps/mcomix.png` and `scalable/apps/mcomix.svg`, the desktop's icons.

The sizes are 16, 22, 24, 32, 48 and 256.

The Windows icon, `../mcomix/images/mcomix.ico`, is not generated: export it by hand, with GIMP for instance.

## The social preview

`social-preview.svg` is the image GitHub shows when the repository is linked: a copy of the scalable icon, the name and a line about it, 1280 × 640 pixels.
`make social-preview.png` renders it; the text is set in Noto Sans.
Upload the PNG under Settings → General → Social preview.

## The original icon

The original icon was drawn by @oxaric, as a 2655 × 1988 pixel PNG; its vector source is lost.
The smaller sizes were scaled down from it, and blurred the smaller they got.
That PNG, `mcomix-large.png`, is in the Git history.
