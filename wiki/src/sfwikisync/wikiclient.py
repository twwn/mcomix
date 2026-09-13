from typing import List, Optional

import requests

from .bearerauth import BearerAuth
from .wikipage import WikiPage

SOURCEFORGE_API_BASE_URL = "https://sourceforge.net/rest/p"

#: Seconds to wait for SourceForge to accept the connection, and then for
#: each part of its answer.  Without a timeout, requests waits for as long
#: as a server that has stopped answering keeps the connection open.
TIMEOUT = 30


class WikiClient:
    def __init__(self, projectname: str, wikiname: str, bearertoken: str) -> None:
        self.projectname = projectname
        self.wikiname = wikiname
        self.auth = BearerAuth(bearertoken)

    def pagenames(self) -> List[str]:
        """Returns a list of all page titles available in the Wiki"""
        response = requests.get(self._generate_url(""), timeout=TIMEOUT)
        pagenames: List[str] = response.json()["pages"]
        return pagenames

    def page(self, pagename: str) -> Optional[WikiPage]:
        """Returns the contents of the given Wiki page."""
        response = requests.get(self._generate_url(pagename), timeout=TIMEOUT)
        if response.status_code == 404:
            return None

        json = response.json()
        return WikiPage(title=json["title"], text=json["text"], labels=json["labels"])

    def create_or_update_page(self, page: WikiPage) -> None:
        """Creates or updates the page with the given title.
        Raises PermissionError if the bearer token isn't accepted, and requests.HTTPError
        if the upload fails for any other reason."""
        response = requests.post(
            self._generate_url(page.title),
            {"labels": page.label_string(), "text": page.text},
            auth=self.auth,
            timeout=TIMEOUT,
        )

        if response.status_code == 401:
            raise PermissionError()
        response.raise_for_status()

    def _generate_url(self, path: str) -> str:
        """Generate a REST API url from the base path determined by script arguments,
        and the given relative path."""
        if path and not path.startswith("/"):
            path = f"/{path}"
        return f"{SOURCEFORGE_API_BASE_URL}/{self.projectname}/{self.wikiname}{path}"
