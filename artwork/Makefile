# Makefile to regenerate icon files from artwork source
#
# Primary input: /artwork/mcomix_icon_artwork.svg
#
# Primary output: /mcomix/images/mcomix.svg
#
# Secondary outputs (generated from /mcomix/images/mcomix.svg):
#   /mcomix/images/mcomix.png (212-pixel-wide bitmap)
#   /mcomix/images/mcomix-$(N).png (packaged $(N)-pixel-wide bitmaps)
#   /share/icons/hicolor/$(N)x$(N)/apps/mcomix.png ($(N)-pixel-wide XDG icons)
#   /share/icons/hicolor/scalable/apps/mcomix.svg (scalable XDG icon)
#
# Separately, from social-preview.svg:
#   social-preview.png (1280x640, GitHub's social preview; not in "all")

PNG_SIZES = 16 22 24 32 48 256
ICON_OUTPUTS := $(foreach i,$(PNG_SIZES),../mcomix/images/mcomix-$(i).png)
XDG_OUTPUTS := $(foreach i,$(PNG_SIZES),../share/icons/hicolor/$(i)x$(i)/apps/mcomix.png)


.PHONY: svg-icon png-icons xdg-icons all
.DEFAULT_GOAL := all

svg-icon: ../mcomix/images/mcomix.svg

../mcomix/images/mcomix.svg: mcomix_icon_artwork.svg
	inkscape -C --export-type=svg --export-plain-svg \
	--export-filename=$@ $<

../share/icons/hicolor/scalable/apps/mcomix.svg: mcomix_icon_artwork.svg
	inkscape -C --export-type=svg --export-plain-svg \
	--export-filename=$@ $<

define PNG_template =
  ../mcomix/images/mcomix-$(1).png: ../mcomix/images/mcomix.svg mcomix_icon_artwork.svg
	inkscape -C -w $(1) --export-type=png \
		--export-filename=$$@ ../mcomix/images/mcomix.svg
endef

define XDG_template =
  ../share/icons/hicolor/$(1)x$(1)/apps/mcomix.png: ../mcomix/images/mcomix.svg mcomix_icon_artwork.svg
	inkscape -C -w $(1) --export-type=png \
		--export-filename=$$@ ../mcomix/images/mcomix.svg
endef

$(foreach i,$(PNG_SIZES),$(eval $(call PNG_template,$(i))))
$(foreach i,$(PNG_SIZES),$(eval $(call XDG_template,$(i))))

../mcomix/images/mcomix.png: ../mcomix/images/mcomix.svg mcomix_icon_artwork.svg
	inkscape -C -w 212 --export-type=png \
		--export-filename=$@ ../mcomix/images/mcomix.svg

png-icons: $(ICON_OUTPUTS) ../mcomix/images/mcomix.png

xdg-icons: $(XDG_OUTPUTS) ../share/icons/hicolor/scalable/apps/mcomix.svg

all: svg-icon png-icons xdg-icons


social-preview.png: social-preview.svg
	inkscape -C -w 1280 -h 640 --export-type=png \
		--export-filename=$@ $<
