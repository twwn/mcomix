"""Convert the wiki's pages from SourceForge's Allura markup to GitHub Markdown.

wiki/Readme.md permits each Allura construct the pages use in exactly one
shape, and names its GitHub equivalent.  This module converts those shapes
and refuses anything else with the page and line that holds it, so that a
page edited out of shape is noticed when it is edited rather than on the day
the pages move.
"""

from __future__ import annotations

import re
from typing import Dict, List, Mapping, NamedTuple, Optional, Set, Tuple

#: The only page the download button and the screenshots may be on.
HOME = "Home"

#: The folder beside the converted pages that the image attachments go into.
IMAGE_DIR = "images"

#: The line that opens and closes a code block.
FENCE = "~~~~~~"

_IMAGE = re.compile(r'\[\[img src="([^"/\\\s]+)" alt="([^"\[\]]+)"\]\]')
_DOWNLOAD_BUTTON = "[[download_button]]"
_SCREENSHOTS = "[[project_screenshots]]"
_TOC = "[TOC]"
_LANGUAGE = re.compile(r":::([\w+-]+)")
_ANCHOR = re.compile(r'<a name="([^"]*)"></a>')
_ATX_HEADING = re.compile(r"#{1,6}\s+(.*?)(?:\s+#+)?\s*")
_SETEXT_UNDERLINE = re.compile(r"=+|-+")
#: A run of backticks, the code, and a run of the same length.
_CODE_SPAN = re.compile(r"(`+).+?(?<!`)\1(?!`)")
#: [text](target), or a bare [Page_Name]; the first group is an image's "!".
_LINK = re.compile(r"(!?)\[([^\[\]]*)\](?:\(([^()\s]+)\))?")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_HTML = re.compile(r"<!--|</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>")

_MACRO_SHAPES = (
    f'[[img src="<file>" alt="<text>"]], {_DOWNLOAD_BUTTON} or {_SCREENSHOTS}, '
    "alone on its line"
)


class ConversionError(ValueError):
    """A construct that is not in the shape wiki/Readme.md permits."""

    def __init__(self, page: str, line: int, message: str) -> None:
        super().__init__(f"{page}.md:{line}: {message}")
        self.page = page
        self.line = line


class Image(NamedTuple):
    """An image attachment, and the page that shows it."""

    page: str
    filename: str
    alt: str


def anchor(heading: str) -> str:
    """The anchor GitHub gives a heading: lower case, with punctuation
    dropped and spaces turned into hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def images(pages: Mapping[str, str]) -> List[Image]:
    """Every image the pages show, page by page in the order of their names.

    Raises ConversionError for a page that is out of shape."""
    return _images(_parse(pages))


def convert(pages: Mapping[str, str], project: str) -> Dict[str, str]:
    """Convert {page name: Allura text} into {page name: GitHub Markdown}.

    The download button becomes a link to the files of the SourceForge
    project named by project, and the screenshots become every image the
    pages show.  Raises ConversionError for the first construct out of
    shape."""
    parsed = _parse(pages)
    screenshots = _images(parsed)
    return {
        name: page.convert(parsed, screenshots, project)
        for name, page in parsed.items()
    }


def _parse(pages: Mapping[str, str]) -> Dict[str, _Page]:
    return {name: _Page(name, text) for name, text in pages.items()}


def _images(pages: Mapping[str, _Page]) -> List[Image]:
    return [image for name in sorted(pages) for image in pages[name].images]


def _image(image: Image) -> str:
    return f"![{image.alt}]({IMAGE_DIR}/{image.filename})"


class _Page:
    """One page's lines, and what converting any page needs to know about
    it: which lines are code, its headings and the images it shows."""

    def __init__(self, name: str, text: str) -> None:
        self.name = name
        self.lines = text.splitlines()
        self.ends_with_newline = text.endswith("\n")
        #: Whether each line belongs to a code block, fences included.
        self.code: List[bool] = []
        #: What each fence line and language line becomes on GitHub; None
        #: for a language line, which the opening fence takes up.
        self.fences: Dict[int, Optional[str]] = {}
        self._find_code()
        #: The first line of each heading, against its last line and text.
        self.headings = self._find_headings()
        self.anchors = self._find_anchors()
        self.images = [
            Image(name, match.group(1), match.group(2))
            for index, match in enumerate(map(_IMAGE.fullmatch, self.lines))
            if match and not self.code[index]
        ]

    def error(self, index: int, message: str) -> ConversionError:
        return ConversionError(self.name, index + 1, message)

    def _find_code(self) -> None:
        opened: Optional[int] = None
        for index, line in enumerate(self.lines):
            if opened is not None:
                if line.startswith("```"):
                    raise self.error(
                        index, "a line of backticks would end the code block on GitHub"
                    )
                if line == FENCE:
                    self.fences[index] = "```"
                    opened = None
                self.code.append(True)
            elif line == FENCE:
                following = self.lines[index + 1] if index + 1 < len(self.lines) else ""
                language = _LANGUAGE.fullmatch(following)
                if not language:
                    raise self.error(
                        index,
                        f"a code block opens with {FENCE} and :::<language> on the next line",
                    )
                self.fences[index] = "```" + language.group(1)
                self.fences[index + 1] = None
                opened = index
                self.code.append(True)
            elif line.startswith(("~~~", "```", ":::")):
                raise self.error(
                    index, f"a code block is fenced with lines of exactly {FENCE}"
                )
            elif line.startswith(("\t", "    ")) and (
                index == 0 or not self.lines[index - 1].strip()
            ):
                raise self.error(
                    index, f"a code block is fenced with {FENCE}, not indented"
                )
            else:
                self.code.append(False)
        if opened is not None:
            raise self.error(opened, "the code block is never closed")

    def _find_headings(self) -> Dict[int, Tuple[int, str]]:
        headings = {}
        for index, line in enumerate(self.lines):
            if self.code[index]:
                continue
            atx = _ATX_HEADING.fullmatch(line)
            if atx:
                headings[index] = (index, atx.group(1))
            elif (
                line.strip()
                and index + 1 < len(self.lines)
                and not self.code[index + 1]
                and _SETEXT_UNDERLINE.fullmatch(self.lines[index + 1])
            ):
                headings[index] = (index + 1, line.strip())
        return headings

    def _find_anchors(self) -> Set[str]:
        """The anchor of every heading, a repeated one numbered as GitHub
        numbers it."""
        anchors = set()
        repeats: Dict[str, int] = {}
        for _, text in self.headings.values():
            slug = anchor(text)
            if slug in repeats:
                repeats[slug] += 1
                anchors.add(f"{slug}-{repeats[slug]}")
            else:
                repeats[slug] = 0
                anchors.add(slug)
        return anchors

    def convert(
        self, pages: Mapping[str, _Page], screenshots: List[Image], project: str
    ) -> str:
        output: List[str] = []
        dropped: Set[int] = set()
        for index, line in enumerate(self.lines):
            if index in dropped:
                continue
            if index in self.fences:
                fence = self.fences[index]
                if fence is not None:
                    output.append(fence)
                continue
            if self.code[index]:
                output.append(line)
                continue

            image = _IMAGE.fullmatch(line)
            target = _ANCHOR.fullmatch(line)
            if image:
                output.append(_image(Image(self.name, image.group(1), image.group(2))))
            elif line in (_DOWNLOAD_BUTTON, _SCREENSHOTS):
                if self.name != HOME:
                    raise self.error(index, f"{line} belongs on {HOME}.md only")
                if line == _DOWNLOAD_BUTTON:
                    output.append(
                        f"[Download](https://sourceforge.net/projects/{project}/files/)"
                    )
                else:
                    for number, screenshot in enumerate(screenshots):
                        if number:
                            output.append("")
                        output.append(_image(screenshot))
            elif target:
                heading = self.headings.get(index + 1)
                if heading is None or anchor(heading[1]) != target.group(1):
                    raise self.error(
                        index,
                        "an anchor line comes directly before the heading GitHub "
                        f"gives the anchor #{target.group(1)}",
                    )
            elif line == _TOC:
                title = self.headings.get(0)
                if (
                    title is None
                    or index != title[0] + 2
                    or self.lines[title[0] + 1].strip()
                ):
                    raise self.error(index, self._toc_shape())
                # The blank line that followed the table of contents would
                # double the one after the title.
                if index + 1 < len(self.lines) and not self.lines[index + 1].strip():
                    dropped.add(index + 1)
            else:
                output.append(self._convert_text(index, line, pages))
        return "\n".join(output) + ("\n" if self.ends_with_newline else "")

    @staticmethod
    def _toc_shape() -> str:
        return f"{_TOC} stands alone directly after the title and a blank line"

    def _convert_text(self, index: int, line: str, pages: Mapping[str, _Page]) -> str:
        """A line of prose, with the code spans in it left as they are."""
        parts = []
        position = 0
        for span in _CODE_SPAN.finditer(line):
            parts.append(self._convert_prose(index, line[position:span.start()], pages))
            parts.append(span.group())
            position = span.end()
        parts.append(self._convert_prose(index, line[position:], pages))
        return "".join(parts)

    def _convert_prose(self, index: int, text: str, pages: Mapping[str, _Page]) -> str:
        if "`" in text:
            raise self.error(index, "a code span ends on the line it starts on")
        if "[[" in text:
            raise self.error(index, f"an Allura macro is {_MACRO_SHAPES}")
        if _HTML.search(text):
            raise self.error(
                index, "no raw HTML is used but an anchor line before a heading"
            )
        return _LINK.sub(lambda match: self._convert_link(index, match, pages), text)

    def _convert_link(
        self, index: int, match: re.Match[str], pages: Mapping[str, _Page]
    ) -> str:
        image, text, target = match.groups()
        if image:
            raise self.error(index, f"an image is written as {_MACRO_SHAPES}")
        if target is None:
            if match.string.startswith("(", match.end()):
                raise self.error(
                    index,
                    f"the target of [{text}] is a page name or a URL, with no "
                    "spaces or title",
                )
            if text == _TOC[1:-1]:
                raise self.error(index, self._toc_shape())
            if text not in pages:
                raise self.error(index, f"[{text}] names no page")
            return f"[{text.replace('_', ' ')}]({text}.md)"
        if _SCHEME.match(target):
            return match.group()
        name, hash_mark, fragment = target.partition("#")
        linked = pages.get(name) if name else self
        if linked is None:
            raise self.error(index, f"[{text}]({target}) names no page")
        if hash_mark and fragment not in linked.anchors:
            raise self.error(
                index, f"no heading on {linked.name}.md has the anchor #{fragment}"
            )
        return f"[{text}]({name + '.md' if name else ''}{hash_mark}{fragment})"
