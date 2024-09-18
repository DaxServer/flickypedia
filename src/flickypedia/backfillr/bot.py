import argparse
import json
import os
from pprint import pprint
from time import perf_counter

import pywikibot
from deepdiff import DeepDiff
from flickr_photos_api import FlickrApi, PhotoIsPrivate, ResourceNotFound
from httpx import Client
from pywikibot import Site
from pywikibot.pagegenerators import SearchPageGenerator

from flickypedia.apis import WikimediaApi
from flickypedia.backfillr.actions import create_actions
from flickypedia.backfillr.flickr_matcher import find_flickr_photo_id_from_sdc, find_flickr_photo_id_from_wikitext
from flickypedia.structured_data import create_sdc_claims_for_existing_flickr_photo, WikidataProperties
from flickypedia.structured_data.statements import create_id_statement


class CuratorBot:
    def __init__(self, _args: argparse.Namespace) -> None:
        self.args = _args

        if os.getenv('PWB_CONSUMER_TOKEN') and os.getenv('PWB_CONSUMER_SECRET') and os.getenv(
                'PWB_ACCESS_TOKEN') and os.getenv('PWB_ACCESS_SECRET'):
            authenticate = (
                os.getenv('PWB_CONSUMER_TOKEN'),
                os.getenv('PWB_CONSUMER_SECRET'),
                os.getenv('PWB_ACCESS_TOKEN'),
                os.getenv('PWB_ACCESS_SECRET'),
            )
            pywikibot.config.authenticate["commons.wikimedia.org"] = authenticate
        else:
            pywikibot.config.password_file = "user-password.py"

        self.site = Site("commons", "commons", user=os.getenv("PWB_USERNAME") or "CuratorBot")
        self.site.login()
        self.user_agent = f"{self.site.username()} / Wikimedia Commons"

        self.http_client = Client(headers={"User-Agent": self.user_agent})
        self.wikimedia_api = WikimediaApi(client=self.http_client)

    def update(self, mid: str, summary: str, existing_claims, new_claims, user = None) -> None:
        actions = create_actions(existing_claims, new_claims, user)
        pywikibot.debug(actions)

        claims = []

        for a in actions:
            if a["action"] == "unknown" or a["action"] == "do_nothing":
                continue
            elif a["action"] == "add_missing":
                claims.append(a["statement"])
            elif a["action"] == "add_qualifiers" or a["action"] == "replace_statement":
                statement = a["statement"]
                statement["id"] = a["statement_id"]
                claims.append(statement)
            else:  # pragma: no cover
                raise ValueError(f"Unrecognised action: {a['action']}")

        if not claims:
            pywikibot.info("No claims to set")
            return

        pywikibot.debug(f"The claims are {claims}")

        payload = {
            "action": "wbeditentity",
            "id": mid,
            "data": json.dumps({"claims": claims}),
            "token": self.site.get_tokens("csrf")['csrf'],
            "summary": summary,
            "tags": "BotSDC",
            "bot": True,
        }
        request = self.site.simple_request(**payload)

        pprint(DeepDiff([], claims))

        try:
            start = perf_counter()
            request.submit()
            pywikibot.info(f"Updating {mid} took {(perf_counter() - start) * 1000:.0f}s")
        except Exception as e:
            pywikibot.critical(f"Failed to update: {e}")

    def get_existing_claims(self, mid):
        start = perf_counter()

        existing_claims = self.wikimedia_api.get_structured_data(mid=mid)

        pywikibot.info(f"Retrieved existing SDC in {(perf_counter() - start) * 1000:.0f} ms")
        pywikibot.debug(existing_claims)

        return existing_claims

    def flickr(self) -> None:
        flickr_api = FlickrApi.with_api_key(api_key=os.getenv("FLICKR_API_KEY"), user_agent=self.user_agent)
        generator = SearchPageGenerator("file: insource:/Category:(Files from )?Flickr/i -haswbstatement:P12120", site=self.site)

        for page in generator:
            page_id = str(page.pageid)
            mid = f"M{page_id}"
            pywikibot.info(f"Processing {mid}")

            url = f"https://commons.wikimedia.org/w/api.php?action=query&prop=categories&format=json&pageids={page_id}"
            try:
                start = perf_counter()
                pageinfo = self.http_client.get(url, follow_redirects=True).json()
                pywikibot.info(f"Fetching Categories from Commons took {(perf_counter() - start) * 1000:.0f} ms")
            except Exception as e:
                pywikibot.error(f"Failed to fetch {url}: {e}")
                continue

            if "title" not in pageinfo["query"]["pages"][page_id]:
                pywikibot.error(f"Skipping as pageinfo is empty")
                continue

            filename = pageinfo["query"]["pages"][page_id]["title"]
            pywikibot.info(f"The filename for {mid} is {filename}")

            categories = [c["title"] for c in pageinfo["query"]["pages"][page_id]["categories"]]
            pywikibot.debug(categories)

            categories_good = [c.startswith("Category:Flickr images") or c.startswith("Category:Files from Flickr") for c in categories]
            if not any(categories_good):
                pywikibot.error(f"Skipping as it was not categorized into Flickr images. Categories: {categories}")
                continue

            existing_claims = self.get_existing_claims(mid)
            pywikibot.debug(existing_claims)

            start = perf_counter()
            wikitext = self.wikimedia_api.get_wikitext(fileid=int(page_id), filename=filename)
            pywikibot.info(f"Retrieved wikitext in {(perf_counter() - start) * 1000:.0f} ms")
            pywikibot.debug(wikitext)

            flickr_id = find_flickr_photo_id_from_sdc(existing_claims)
            if flickr_id is None:
                flickr_id = find_flickr_photo_id_from_wikitext(wikitext)
            if flickr_id is None:
                pywikibot.error(f"Unable to find Flickr ID for {filename}")
                continue
            pywikibot.debug(flickr_id)

            try:
                start = perf_counter()
                single_photo = flickr_api.get_single_photo(photo_id=flickr_id["photo_id"])
                pywikibot.info(f"Retrieved Flickr photo in {(perf_counter() - start) * 1000:.0f} ms")
                new_claims = create_sdc_claims_for_existing_flickr_photo(single_photo)
                user = single_photo["owner"]
            except (PhotoIsPrivate, ResourceNotFound) as e:
                pywikibot.warning(f"{flickr_id['photo_id']} warning: {e}")
                new_claims = {
                    "claims": [
                        create_id_statement(id=flickr_id["photo_id"], which_id=WikidataProperties.FlickrPhotoId)
                    ]
                }
                user = None

            pywikibot.debug(new_claims)
            pywikibot.debug(user)

            self.update(
                mid,
                "Update [[Commons:Structured data|SDC]] based on metadata from Flickr. Task #2",
                existing_claims,
                new_claims,
                user,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--module", help="Which module to run", required=True, type=str, choices=["flickr"])

    args = parser.parse_args()

    if args.module == "flickr":
        CuratorBot(args).flickr()
    else:
        raise ValueError("Invalid module")
