from ..types import NewStatement, QualifierValues, to_wikidata_entity_value, create_qualifiers
from ..wikidata_entities import WikidataEntities
from ..wikidata_properties import WikidataProperties


def create_license_statement(license_id: str, title: str | None = None, author_name_string: str | None = None) -> NewStatement:
    """
    Create a structured data statement for copyright license.
    """
    try:
        wikidata_license_id = WikidataEntities.Licenses[license_id]
    except KeyError:
        raise ValueError(f"Unrecognised license ID: {license_id!r}")

    qualifiers: list[QualifierValues] = []

    if 'cc-by-sa-2.0' == license_id:
        if title is not None:
            qualifiers.append({
                "property": WikidataProperties.Title,
                "value": {"text": title, "language": "en"},
                "type": "monolingualtext",
            })

        if author_name_string is not None:
            qualifiers.append({
                "property": WikidataProperties.AuthorName,
                "value": author_name_string,
                "type": "string",
            })

    return {
        "mainsnak": {
            "snaktype": "value",
            "property": WikidataProperties.CopyrightLicense,
            "datavalue": to_wikidata_entity_value(entity_id=wikidata_license_id),
        },
        "qualifiers": create_qualifiers(qualifiers),
        "qualifiers-order": [q["property"] for q in qualifiers],
        "type": "statement",
    }
