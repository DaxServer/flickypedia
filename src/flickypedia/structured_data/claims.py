import datetime
import typing

from flickr_photos_api import SinglePhoto, UserInfo

from .flickr_users import FlickrUsers
from .statements import (
    create_bhl_page_id_statement,
    create_copyright_status_statement,
    create_date_taken_statement,
    create_flickr_creator_statement,
    create_id_statement,
    create_license_statement,
    create_location_statement,
    create_published_in_statement,
    create_source_statement,
)
from .types import NewClaims


def _create_sdc_claims_for_flickr_photo(
    mode: typing.Literal["new_photo", "existing_photo"],
    photo: SinglePhoto | None = None,
    retrieved_at: datetime.datetime | None = None,
    user: UserInfo | None = None,
    photo_id: str | None = None,
    photo_url: str | None = None,
) -> NewClaims:
    """
    Creates a complete structured data claim for a Flickr photo.

    This is the main entry point into this file for the rest of Flickypedia.
    """
    from . import WikidataEntities, WikidataProperties

    statements = []

    if photo is not None:
        photo_id_statement = create_id_statement(id=photo["id"], which_id=WikidataProperties.FlickrPhotoId)
        creator_statement = create_flickr_creator_statement(user=photo["owner"])

        statements = [
            photo_id_statement,
            creator_statement,
        ]
    else:
        if photo_id is not None:
            statements.append(create_id_statement(id=photo_id, which_id=WikidataProperties.FlickrPhotoId))

        if user is not None:
            statements.append(create_flickr_creator_statement(user=user))

    # Note 1: the "Original" size is not guaranteed to be available
    # for all Flickr photos (in particular those who've disabled
    # downloads).
    #
    # Downloads are always available for CC-licensed or public domain
    # photos, which will be any new uploads, but they may not be available
    # if we're looking at photos whose license have changed since they
    # were initial uploaded to Wikimedia Commons.
    #
    # Note 2: Flickr users can replace a photo after it's uploaded, and
    # without comparing the two files we can't be sure the JPEG hasn't
    # changed since it was copied to Wikimedia Commons.
    #
    # We only write the original URL for new photos; we can't be sure
    # it's correct for existing photos.
    original_url: str | None = None

    if photo is not None and mode == "new_photo":
        try:
            original_size = [s for s in photo["sizes"] if s["label"] == "Original"][0]
        except IndexError:
            raise
        else:
            original_url = original_size["source"]

    described_at_url = photo["url"] if photo is not None else photo_url

    if described_at_url is not None:
        source_statement = create_source_statement(
            described_at_url=described_at_url,
            operator=WikidataEntities.Flickr,
            original_url=original_url,
            retrieved_at=retrieved_at,
        )

        statements.append(source_statement)

    # We only include the license statement for new uploads -- that field
    # is already pretty well-populated for existing photos, and licenses
    # can have changed since a photo was initially uploaded to Flickr.
    #
    # TODO: Investigate whether we can do anything here with license history.
    if photo is not None:
        if photo["license"]["id"] in WikidataEntities.Licenses:
            license_statement = create_license_statement(
                license_id=photo["license"]["id"],
                title=photo["title"] if "title" in photo else None,
                author_name_string=photo["owner"]["realname"] or photo["owner"]["username"],
            )

            copyright_statement = create_copyright_status_statement(
                license_id=photo["license"]["id"]
            )

            statements.extend([license_statement, copyright_statement])

        location_statement = create_location_statement(location=photo["location"])

        if location_statement is not None:
            statements.append(location_statement)

        if photo["date_taken"] is not None:
            statements.append(create_date_taken_statement(date_taken=photo["date_taken"]))

        # Add the BHL Photo ID statement, but only if this is the BHL user.
        if photo["owner"]["id"] == FlickrUsers.BioDivLibrary:
            bhl_page_id_statement = create_bhl_page_id_statement(
                photo_id=photo["id"], machine_tags=photo["machine_tags"]
            )

            if bhl_page_id_statement is not None:
                statements.append(bhl_page_id_statement)

    published_in_statement = create_published_in_statement(
        published_in=WikidataEntities.Flickr,
        date_posted=photo["date_posted"] if photo is not None else None,
    )

    statements.append(published_in_statement)

    return {"claims": statements}


def create_sdc_claims_for_new_flickr_photo(
    photo: SinglePhoto, retrieved_at: datetime.datetime
) -> NewClaims:
    """
    Create the SDC claims for a new upload to Wikimedia Commons.
    """
    return _create_sdc_claims_for_flickr_photo(
        mode="new_photo", photo=photo, retrieved_at=retrieved_at
    )


def create_sdc_claims_for_existing_flickr_photo(
        photo: SinglePhoto | None = None,
        user: UserInfo | None = None,
        photo_id: str | None = None,
        photo_url: str | None = None,
) -> NewClaims:
    """
    Create the SDC claims for a photo which has already been uploaded to WMC.

    This is slightly different to the SDC we create for new uploads:

    *   We don't write a "retrieved at" qualifier, because it would tell
        you when the bot ran rather than when the photo was uploaded to Commons.

    *   We don't include a copyright license/status statement.  Flickr users
        often change their license after it was copied to Commons, and then
        the backfillr bot gets confused because it doesn't know how to map
        the new license, or it doesn't know how to reconcile the conflicting SDC.

    """
    return _create_sdc_claims_for_flickr_photo(mode="existing_photo", photo=photo, user=user, photo_id=photo_id, photo_url=photo_url)
