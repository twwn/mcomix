# Makefile to regenerate icon files from artwork source
#
# Primary input: /artwork/mcomix_icon_artwork.svg
#
# Primary output: $(SVG), the scalable icon MComix carries
#
# Secondary outputs (generated from $(SVG)):
#   /mcomix/images/mcomix.png (212-pixel-wide bitmap)
#   /mcomix/images/icons/hicolor/$(N)x$(N)/apps/mcomix.png (packaged $(N)-pixel-wide bitmaps)
#   /share/icons/hicolor/$(N)x$(N)/apps/mcomix.png ($(N)-pixel-wide XDG icons)
#   /share/icons/hicolor/scalable/apps/mcomix.svg (scalable XDG icon)
#
# Separately, from social-preview.svg:
#   social-preview.png (1280x640, GitHub's social preview; not in "all")

PNG_SIZES = 16 22 24 32 48 256
# The icon is 4:3, and an icon theme's <N>x<N> folder holds square
# pictures: each is centred on a transparent square (ImageMagick).
SQUARE := magick -background none -gravity center \
	-define png:exclude-chunks=date,time
# Every output is optimised as it is written: svgo for an SVG, pngquant
# for a PNG, which it leaves alone (status 98) where the palette version
# would come out larger, as it does for the smallest icons.
SVGO := svgo -q
PNGQUANT := pngquant --speed 1 --skip-if-larger --ext .png --force
SVG := ../mcomix/images/icons/hicolor/scalable/apps/mcomix.svg
ICON_OUTPUTS := $(foreach i,$(PNG_SIZES),../mcomix/images/icons/hicolor/$(i)x$(i)/apps/mcomix.png)
XDG_OUTPUTS := $(foreach i,$(PNG_SIZES),../share/icons/hicolor/$(i)x$(i)/apps/mcomix.png)


.PHONY: svg-icon png-icons xdg-icons all
.DEFAULT_GOAL := all

svg-icon: $(SVG)

$(SVG): mcomix_icon_artwork.svg
	inkscape -C --export-type=svg --export-plain-svg \
	--export-filename=$@ $<
	$(SVGO) $@

../share/icons/hicolor/scalable/apps/mcomix.svg: mcomix_icon_artwork.svg
	inkscape -C --export-type=svg --export-plain-svg \
	--export-filename=$@ $<
	$(SVGO) $@

define PNG_template =
  ../mcomix/images/icons/hicolor/$(1)x$(1)/apps/mcomix.png: $(SVG) mcomix_icon_artwork.svg
	inkscape -C -w $(1) --export-type=png \
		--export-filename=$$@ $(SVG)
	$(SQUARE) $$@ -strip -extent $(1)x$(1) PNG32:$$@
	$(PNGQUANT) $$@ || test $$$$? = 98
endef

define XDG_template =
  ../share/icons/hicolor/$(1)x$(1)/apps/mcomix.png: $(SVG) mcomix_icon_artwork.svg
	inkscape -C -w $(1) --export-type=png \
		--export-filename=$$@ $(SVG)
	$(SQUARE) $$@ -strip -extent $(1)x$(1) PNG32:$$@
	$(PNGQUANT) $$@ || test $$$$? = 98
endef

$(foreach i,$(PNG_SIZES),$(eval $(call PNG_template,$(i))))
$(foreach i,$(PNG_SIZES),$(eval $(call XDG_template,$(i))))

../mcomix/images/mcomix.png: $(SVG) mcomix_icon_artwork.svg
	inkscape -C -w 212 --export-type=png \
		--export-filename=$@ $(SVG)
	$(PNGQUANT) $@ || test $$? = 98

png-icons: $(ICON_OUTPUTS) ../mcomix/images/mcomix.png

xdg-icons: $(XDG_OUTPUTS) ../share/icons/hicolor/scalable/apps/mcomix.svg

all: svg-icon png-icons xdg-icons


social-preview.png: social-preview.svg
	inkscape -C -w 1280 -h 640 --export-type=png \
		--export-filename=$@ $<
	$(PNGQUANT) $@ || test $$? = 98
