"""
Create Wikitext for display on Wikimedia Commons.

Note that we primarily rely on structured data to put information on
the page using the Lua-driven {{Information}} template, so we don't
need to put in much text ourself.

== Useful reading ==

*   Help:Wikitext
    https://en.wikipedia.org/wiki/Help:Wikitext

"""

from typing import List


def create_wikitext(license_id: str, categories: List[str]) -> str:
    """
    Creates the Wikitext for a Flickr photo being uploaded to Wiki Commons.
    """

    lines = [
        "=={{int:filedesc}}==",
        "{{Information}}",
        "",
        "=={{int:license-header}}==",
        "{{%s}}" % license_id,
        "",
    ]

    for category_name in categories:
        lines.append(f"[[Category:{category_name}]]")

    return "\n".join(lines).strip()
