from __future__ import annotations


def create_external_link(relative_url: str, type_title: str, title: str | None, embedded: bool) -> Link:
    import crystal.doc.html.soup as soup

    # HACK: Reuse existing link class rather than create a new one just for the generic case
    return soup.HtmlLink.create_external(relative_url, type_title, title, embedded)


class Document:  # abstract
    def __str__(self) -> str:
        raise NotImplementedError()


class Link:  # abstract
    title: str | None
    type_title: str
    embedded: bool
    
    def _get_relative_url(self) -> str:
        raise NotImplementedError()
    def _set_relative_url(self, url: str) -> None:
        raise NotImplementedError()
    relative_url = property(_get_relative_url, _set_relative_url)
