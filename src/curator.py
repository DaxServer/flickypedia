import argparse
import json
import os
import time
from pprint import pprint
from time import perf_counter

import flickr_url_parser
import httpx
import pywikibot
from deepdiff import DeepDiff
from flickr_photos_api import FlickrApi, PhotoIsPrivate, ResourceNotFound, UserDeleted
from httpx import Client
from pywikibot import Site, Page
from pywikibot.pagegenerators import SearchPageGenerator
from redis import Redis

from flickypedia.apis import WikimediaApi
from flickypedia.backfillr.actions import create_actions
from flickypedia.backfillr.flickr_matcher import find_flickr_photo_id_from_sdc, \
    find_flickr_photo_id_from_parsed_wikitext, FindResult
from flickypedia.structured_data import create_sdc_claims_for_existing_flickr_photo, NewClaims


def extract_flickr_id(existing_claims, wikitext_parsed) -> FindResult | None:
    flickr_id = None

    try:
        flickr_id = find_flickr_photo_id_from_sdc(existing_claims)

        if flickr_id is None or flickr_id["url"] is None:
            flickr_id_wikitext = find_flickr_photo_id_from_parsed_wikitext(wikitext_parsed)

            if flickr_id_wikitext is not None:
                if flickr_id is not None and flickr_id["photo_id"] != flickr_id_wikitext["photo_id"]:
                    pywikibot.error(f"Photo ID mismatch: SDC {flickr_id} vs Wikitext {flickr_id_wikitext}")
                else:
                    flickr_id = flickr_id_wikitext
    except Exception as e:
        pywikibot.warning(f"Warning: {e}")

    return flickr_id


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
        self.pd_us_templates = [t['title'] for t in httpx.get('https://petscan.wmcloud.org/?psid=33444757&format=json').json()['*'][0]['a']['*']]

        self.flickr_api = FlickrApi.with_api_key(api_key=os.getenv("FLICKR_API_KEY"), user_agent=self.user_agent)
        self.redis = Redis(host='redis.svc.tools.eqiad1.wikimedia.cloud', db=9)
        self.redis_prefix = 'xQ6cz5J84Viw/K6FIcOH1kxJjfiS8jO56AoSmhBgO/A='

    def update(self, mid: str, summary: str, existing_claims, new_claims, user = None, is_us_pd: bool = False) -> None:
        actions = create_actions(existing_claims, new_claims, user, is_us_pd)
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
            elif a["action"] == "remove_statement":
                claims.append({
                    "id": a["statement_id"],
                    "remove": "",
                })
            else:
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
            # request.submit()
            pywikibot.info(f"Updating {mid} took {(perf_counter() - start):.1f} s")
        except Exception as e:
            pywikibot.critical(f"Failed to update: {e}")

    def get_existing_claims(self, mid):
        start = perf_counter()

        existing_claims = self.wikimedia_api.get_structured_data(mid=mid)

        pywikibot.info(f"Retrieved existing SDC in {(perf_counter() - start) * 1000:.0f} ms")
        pywikibot.debug(existing_claims)

        return existing_claims

    def is_us_pd(self, raw_extracted_templates) -> bool:
        templates = [t.replace(' ', '_') for (t, x) in raw_extracted_templates]

        return any([t in self.pd_us_templates for t in templates])

    def process_page(self, page: Page, summary: str | None = None, inject_us_pd: bool = False) -> None:
        page_id = page.pageid
        mid = f"M{page_id}"
        pywikibot.info(f"Processing {mid}")

        filename = page.title()
        pywikibot.info(f"URL for {mid}: {page.full_url()}")

        existing_claims = self.get_existing_claims(mid)
        pywikibot.debug(existing_claims)

        start = perf_counter()
        wikitext_parsed = self.wikimedia_api.get_wikitext(fileid=page_id, filename=filename)
        pywikibot.info(f"Retrieved parsed wikitext in {(perf_counter() - start) * 1000:.0f} ms")
        pywikibot.debug(wikitext_parsed)

        is_us_pd = self.is_us_pd(page.raw_extracted_templates)
        pywikibot.info(f"Is US PD: {is_us_pd}")

        flickr_id = extract_flickr_id(existing_claims, wikitext_parsed)

        if flickr_id is None:
            pywikibot.error("Unable to find Flickr ID")
            self.redis.set(redis_key, 1)
            return

        pywikibot.info(flickr_id)

        new_claims, user = self.get_flickr_photo(flickr_id, is_us_pd)

        if user is None:
            new_claims, user = self.get_flickr_user(flickr_id, is_us_pd)

        pywikibot.debug(new_claims)
        pywikibot.debug(user)

        self.update(
            mid,
            summary or "Update [[Commons:Structured data|SDC]] based on metadata from Flickr. Task #2",
            existing_claims,
            new_claims,
            user,
            inject_us_pd and is_us_pd,
        )

    def get_flickr_photo(self, flickr_id: FindResult, is_us_pd: bool) -> tuple[NewClaims, str | None]:
        new_claims = NewClaims(claims=[])
        user = None

        redis_key_photo = f'{self.redis_prefix}:{flickr_id["photo_id"]}:photo'

        # Check Redis cache if Flickr photo is not available
        if self.redis.get(redis_key_photo) is not None:
            pywikibot.warning(f"[{flickr_id['photo_id']}] Flickr photo skipped due to Redis cache")
            return new_claims, user

        try:
            start = perf_counter()
            single_photo = self.flickr_api.get_single_photo(photo_id=flickr_id["photo_id"])
            pywikibot.info(f"Retrieved Flickr photo in {(perf_counter() - start) * 1000:.0f} ms")

            new_claims = create_sdc_claims_for_existing_flickr_photo(photo=single_photo, is_us_pd=is_us_pd)
            user = single_photo["owner"]
        except (PhotoIsPrivate, ResourceNotFound) as e:
            pywikibot.warning(f"[{flickr_id['photo_id']}] {e}")
            self.redis.set(redis_key_photo, 1)
        except Exception as e:
            pywikibot.error(f"[{flickr_id['photo_id']}] {e}")
            time.sleep(60)

        return new_claims, user

    def get_flickr_user(self, flickr_id: FindResult, is_us_pd: bool) -> tuple[NewClaims, str | None]:
        new_claims = NewClaims(claims=[])
        user = None

        redis_key_user = f'{self.redis_prefix}:{flickr_id["photo_id"]}:user'

        # Check Redis cache if Flickr user is not available from Photo API
        if self.redis.get(redis_key_user) is not None:
            pywikibot.warning(f"[{flickr_id['photo_id']}] Flickr user skipped due to Redis cache")
            return new_claims, user

        try:
            start = perf_counter()
            user_url = flickr_url_parser.parse_flickr_url(flickr_id["url"])["user_url"]
            user = self.flickr_api.get_user(user_url=user_url)
            pywikibot.info(f"Retrieved Flickr user in {(perf_counter() - start) * 1000:.0f} ms")

            new_claims = create_sdc_claims_for_existing_flickr_photo(user=user, photo_id=flickr_id["photo_id"],
                                                                     photo_url=flickr_id["url"], is_us_pd=is_us_pd)
        except (UserDeleted, ResourceNotFound) as e:
            pywikibot.warning(f"[{flickr_id['photo_id']}] {e}")
            self.redis.set(redis_key_user, 1)
        except Exception as e:
            pywikibot.error(f"[{flickr_id['photo_id']}] {e}")
            time.sleep(60)

        return new_claims, user

    def flickr(self) -> None:
        search = 'file: deepcat:"Files from Flickr" -haswbstatement:P170'
        pywikibot.info(search)
        generator = SearchPageGenerator(search, site=self.site)

        for page in generator:
            self.process_page(page)

    def flickr_fix(self):
        search = 'file: deepcat:"Files from Flickr" haswbstatement:P6216=Q88088423'
        pywikibot.info(search)
        generator = SearchPageGenerator(search, site=self.site)

        for page in generator:
            if 'CuratorBot' not in page.contributors():
                pywikibot.info(f"Skipping {page.title()} as it was not edited by CuratorBot")
                continue

            self.process_page(page, "Fix US PD [[Commons:Structured data|SDC]] based on metadata from Flickr. Task #2, see [[User_talk:DaxServer/Archive_2#CuratorBot_adding_incorrect_copyright_statements|discussion]]", True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--module", help="Which module to run", required=True, type=str, choices=["flickr", "flickrfix"])

    args = parser.parse_args()

    if args.module == "flickr":
        CuratorBot(args).flickr()
    elif args.module == "flickrfix":
        CuratorBot(args).flickr_fix()
    else:
        raise ValueError("Invalid module")
