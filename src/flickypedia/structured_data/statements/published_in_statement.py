import datetime

from ..types import (
    NewStatement,
    QualifierValues,
    create_qualifiers,
    to_wikidata_entity_value,
)
from ..wikidata_properties import WikidataProperties


def create_published_in_statement(published_in: str, date_posted: datetime.datetime | None) -> NewStatement:
    """
    Create a "Published In" statement for the date a photo was posted.
    """
    qualifier_values: list[QualifierValues] = []

    if date_posted is not None:
        qualifier_values.append({
            "property": WikidataProperties.PublicationDate,
            "date": date_posted,
            "precision": "day",
            "type": "date",
        })

    return {
        "mainsnak": {
            "snaktype": "value",
            "property": WikidataProperties.PublishedIn,
            "datavalue": to_wikidata_entity_value(entity_id=published_in),
        },
        "qualifiers": create_qualifiers(qualifier_values),
        "qualifiers-order": [q["property"] for q in qualifier_values],
        "type": "statement",
    }
