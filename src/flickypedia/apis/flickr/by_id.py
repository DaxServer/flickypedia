import datetime

from flask import current_app
from flickr_photos_api import FlickrApi


def get_photo_by_id(photo_id: str):
    retrieved_at = datetime.datetime.now()

    api = FlickrApi.with_api_key(
        api_key=current_app.config["FLICKR_API_KEY"],
        user_agent=current_app.config["USER_AGENT"],
    )

    photo = api.get_single_photo(photo_id=photo_id)

    return {
        "photo": photo,
        "retrieved_at": retrieved_at,
    }
