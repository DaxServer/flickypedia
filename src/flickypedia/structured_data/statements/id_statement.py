from ..types import NewStatement, to_wikidata_string_value


def create_id_statement(id: str, which_id: str) -> NewStatement:
    """
    Creates a XYZ ID statement.

    This is a main statement rather than a qualifier on another statement;
    this is to match the convention of e.g. YouTube video ID, Flickr photo ID.
    """
    return {
        "mainsnak": {
            "datavalue": to_wikidata_string_value(value=id),
            "property": which_id,
            "snaktype": "value",
        },
        "type": "statement",
    }
