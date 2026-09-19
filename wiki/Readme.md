# Wiki synchronization

## Summary

`sfwikisync` copies the pages of MComix' SourceForge wiki to and from the Markdown files in the `content` folder beside this file, one file per page, named after the page. It also converts those files to GitHub Markdown, for the day the pages move.

## Setup

1. Create a virtual environment and enter it: `python3 -m venv env`, then `source env/bin/activate`.
2. Install the tool: `pip install .`. To work on the tool itself, install it in editable mode with its development dependencies instead: `pip install -e '.[dev]'`.

## Commands

Command | What it does
--------|-------------
`sfwikisync -p mcomix pull` | Downloads every wiki page into `content`. **Existing files are overwritten without asking**, so anything edited locally and not pushed yet is lost.
`sfwikisync -p mcomix push` | Uploads every file in `content` whose text differs from its page, creating pages that do not exist yet. The page's labels are kept.
`sfwikisync -p mcomix github` | Converts every file in `content` to GitHub Markdown, as [Moving the pages to GitHub](#moving-the-pages-to-github) describes, and writes it into `github`, overwriting a file of the same name. The images the pages show are copied from `images` into `github/images`. A construct out of its shape, or an image `images` does not hold, stops the conversion before anything is written, naming the page and the line, or the image and its page.

`-w` names another wiki than `wiki`, `-d` another folder than `content`, `-o` another folder than `github`, and `-i` another folder than `images`.

Pushing needs a bearer token. On SourceForge's [OAuth management page](https://sourceforge.net/auth/oauth/), register an application (named *sfwikisync*, for example) and generate a bearer token for it. Pass it in the environment:

~~~~~~
:::bash
export SFWIKISYNC_BEARER_TOKEN=<token>
sfwikisync -p mcomix push
~~~~~~

`-b <token>` works as well, but a token on the command line is kept in the shell's history and shown in the process list.

## Moving the pages to GitHub

The pages use SourceForge's Allura markup, which GitHub does not render. Each Allura construct they use appears in exactly one shape, so that a script can convert every page without a person reading it. Keep to these shapes when editing a page. The `github` command converts them as the table says and refuses anything else, and MComix' test suite converts every page (`test/test_wiki.py`), so a page edited out of shape fails the tests.

Construct | The one permitted shape | GitHub equivalent
----------|-------------------------|------------------
Image | `[[img src="<file>" alt="<text>"]]` alone on its line, always with `alt`, `src` being the attachment's file name with no path | `![<text>](images/<file>)`, the file taken from `wiki/images`, where the attachments are kept
Download button | `[[download_button]]` alone on its line, on `Home.md` only | A link to the project's files on SourceForge, where the releases are
Screenshots | `[[project_screenshots]]` alone on its line, on `Home.md` only | Every image the pages show, from `images/`
Table of contents | `[TOC]` alone on its line, directly after the page title and a blank line, or not at all | Nothing: GitHub draws its own outline
Code block | A line of exactly six tildes, `:::<language>` on the next line (`text` where there is no language), the code, and six tildes again. No indented code blocks, so no line that follows a blank line starts with a tab or four spaces | ```` ```<language> ````, the code, ```` ``` ````
Link to another page | `[Page_Name]`, where `Page_Name` is the file name without `.md` | `[Page Name](Page_Name.md)`
Link to another page, other text | `[text](Page_Name)`, or `[text](Page_Name#<slug>)` into it | `[text](Page_Name.md)`, or `[text](Page_Name.md#<slug>)`
Link into a page | `<a name="<slug>"></a>` on the line before the heading, `<slug>` being the heading as GitHub makes an anchor of it: lower case, spaces as hyphens, punctuation dropped | Delete the anchor line; links to `#<slug>` still land

Square brackets inside code, such as `pip install '.[dev]'`, are code rather than links; anywhere else they are a link, which has to land on a page and, with a `#<slug>`, on one of its headings. A code span ends on the line it starts on. No other raw HTML is used: a line break is a blank line. `&rarr;` is an HTML entity, which GitHub renders as it is.

Headings keep the style of their page. `===` and `---` underlines give the first two levels, and `###` or `####` the levels below them; both render on GitHub as they are, as do the pipe tables.

Page names, file names and link targets are the same word, so no file is renamed.

The image attachments on the SourceForge wiki are:

- `mcomix-mainwindow.png`, on `Documentation.md`;
- `mcomix-library.png`, on `Documentation.md`;
- `mcomix-external-commands.png`, on `External_Commands.md`.
