#!/usr/bin/env python3

import argparse
import enum
import glob
import logging
import os
import pathlib
import shutil
import sys

from . import github
from .wikiclient import WikiClient
from .wikipage import WikiPage

#: The environment variable the bearer token is read from.
TOKEN_VARIABLE = "SFWIKISYNC_BEARER_TOKEN"


class Operations(enum.Enum):
    pull = 0
    push = 1
    github = 2


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=pathlib.Path(sys.argv[0]).name,
        description="Synchronize a folder of Markdown documents with an Allura wiki hosted by SourceForge",
    )
    parser.add_argument("-p", "--project", required=True)
    parser.add_argument("-w", "--wikiname", default="wiki")
    parser.add_argument("-d", "--contentdir", default="content")
    parser.add_argument("-o", "--outdir", default="github")
    parser.add_argument("-i", "--imagedir", default="images")
    # A token given on the command line lands in the shell's history and in
    # the process list, so the environment is the better place for it.
    parser.add_argument(
        "-b", "--bearertoken", default=os.environ.get(TOKEN_VARIABLE)
    )
    parser.add_argument(
        "operation", choices=[enumvalue.name for enumvalue in Operations]
    )
    args = parser.parse_args()

    if args.operation == Operations.push.name and not args.bearertoken:
        parser.error(
            f"The {Operations.push.name} operation requires authentication: "
            f"set {TOKEN_VARIABLE}, or pass --bearertoken"
        )

    return args


def pull(client: WikiClient, contentdir: str) -> None:
    """Read the contents of all wiki pages, and write them into the content directory.
    Existing files are overwritten without confirmation."""
    logging.info("Retrieving list of Wiki pages")
    pagenames = client.pagenames()
    basedir = pathlib.Path(contentdir)
    for pagename in pagenames:
        page = client.page(pagename)
        if not page:
            logging.error(f"Page '{pagename}' could not be downloaded")
            continue
        else:
            logging.info(f"Downloaded '{pagename}'")

        page_path = basedir / page.filename()
        # The API keeps page text with Windows line endings, which the files
        # in the repository do not have; push puts them back.
        with open(page_path, "w", encoding="utf-8", newline="\n") as fp:
            fp.write(page.text.replace("\r\n", "\n"))


def read_page_text(path: pathlib.Path) -> str:
    """Reads the content of the given path, converting line endings to Windows endings if needed (since
    the SF API keeps page text with Windows line endings)."""
    with open(path, "r", encoding="utf-8") as fp:
        page_text = fp.read()
        if "\r\n" not in page_text and "\n" in page_text:
            page_text = page_text.replace("\n", "\r\n")
        return page_text


def push(client: WikiClient, contentdir: str) -> None:
    """Reads all markdown files from the content directory, and creates matching wiki pages for them.
    Update is only performed if the pages differ."""
    for filename in glob.glob(f"{contentdir}/*.md"):
        path = pathlib.Path(filename)
        page_title = path.stem
        page_text = read_page_text(path)

        # Copy labels from old page if they exist, since the script has no way to store labels at the moment
        old_page = client.page(page_title)
        labels = old_page.labels if old_page else []
        new_page = WikiPage(title=page_title, text=page_text, labels=labels)

        if not old_page or old_page.text != new_page.text:
            client.create_or_update_page(new_page)
            logging.info(f"Updated '{page_title}'")
        else:
            logging.info(f"No change to '{page_title}'")


def convert_to_github(
    project: str, contentdir: str, outdir: str, imagedir: str
) -> bool:
    """Converts all markdown files in the content directory to GitHub Markdown, and writes them into
    the output directory, with the images they show copied from the image directory into an images
    folder there. Existing files are overwritten without confirmation. Returns False, having written
    nothing, if a page is out of the shapes wiki/Readme.md permits or shows an image the image
    directory does not hold."""
    pages = {
        path.stem: path.read_text(encoding="utf-8")
        for path in sorted(pathlib.Path(contentdir).glob("*.md"))
    }
    try:
        converted = github.convert(pages, project)
    except github.ConversionError as error:
        logging.error(error)
        return False
    source = pathlib.Path(imagedir)
    images = github.images(pages)
    missing = [image for image in images if not (source / image.filename).is_file()]
    for image in missing:
        logging.error(
            f"'{image.filename}', shown on '{image.page}', is not in {source}"
        )
    if missing:
        return False

    basedir = pathlib.Path(outdir)
    basedir.mkdir(parents=True, exist_ok=True)
    for name, text in converted.items():
        (basedir / f"{name}.md").write_text(text, encoding="utf-8")
        logging.info(f"Converted '{name}'")
    target = basedir / github.IMAGE_DIR
    target.mkdir(exist_ok=True)
    for image in images:
        shutil.copyfile(source / image.filename, target / image.filename)
        logging.info(f"Copied '{image.filename}'")
    return True


def main() -> int:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s: %(message)s", level=logging.INFO
    )
    program_args = parse_arguments()
    if program_args.operation == Operations.github.name:
        converted = convert_to_github(
            program_args.project,
            program_args.contentdir,
            program_args.outdir,
            program_args.imagedir,
        )
        return 0 if converted else 1

    client = WikiClient(
        program_args.project, program_args.wikiname, program_args.bearertoken
    )

    if program_args.operation == Operations.pull.name:
        pull(client, program_args.contentdir)
    elif program_args.operation == Operations.push.name:
        push(client, program_args.contentdir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
