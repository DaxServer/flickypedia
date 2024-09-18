import argparse
import csv
import json
import os
from pprint import pprint
from tempfile import NamedTemporaryFile
from time import perf_counter

import pywikibot
from deepdiff import DeepDiff
from flickr_photos_api import FlickrApi
from httpx import Client
from pywikibot import Site
from pywikibot.pagegenerators import SearchPageGenerator

from flickypedia.apis import WikimediaApi
from flickypedia.backfillr.backfillr import Backfillr


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-until", help="Skip until this MID", required=False, type=str)
    args = parser.parse_args()
    skip = args.skip_until is not None

    if os.getenv('PWB_CONSUMER_TOKEN') and os.getenv('PWB_CONSUMER_SECRET') and os.getenv('PWB_ACCESS_TOKEN') and os.getenv('PWB_ACCESS_SECRET'):
        authenticate = (
            os.getenv('PWB_CONSUMER_TOKEN'),
            os.getenv('PWB_CONSUMER_SECRET'),
            os.getenv('PWB_ACCESS_TOKEN'),
            os.getenv('PWB_ACCESS_SECRET'),
        )
        pywikibot.config.authenticate['commons.wikimedia.org'] = authenticate
    else:
        pywikibot.config.password_file = os.path.relpath(os.path.join(os.path.dirname(__file__), "../../../user-password.py"))

    login_username = os.getenv("PWB_USERNAME") or "CuratorBot"
    site = Site("commons", "commons", user=login_username)
    site.login()

    generator = SearchPageGenerator('file: insource:flickr insource:"Category:Flickr" -haswbstatement:P12120', site=site)
    flickr_api = FlickrApi.with_api_key(
        api_key=os.getenv("FLICKR_API_KEY"),
        user_agent=os.getenv("USER_AGENT"),
    )
    wikimedia_api = WikimediaApi(client=Client(headers={
        "User-Agent": os.getenv("USER_AGENT"),
    }))

    generic_http = Client(headers={"User-Agent": os.getenv("USER_AGENT")})
    backfillr = Backfillr(flickr_api=flickr_api, wikimedia_api=wikimedia_api)

    file = NamedTemporaryFile(mode="w")

    # with generic_http.stream("GET", "https://files.daxserver.com/files/flickr.csv") as response:
    #     for text in response.iter_text():
    #         file.write(text)

    with open(file.name) as f:
        # reader = csv.reader(f)

        for page in generator:
        # while row := next(reader):
        #     if skip:
        #         if row[0].split('/')[-1] != args.skip_until:
        #             pywikibot.info(f"Skipping {row[0]}")
        #             continue
        #         else:
        #             skip = False

            # mid = row[0].split('/')[-1]
            mid = f"M{page.pageid}"
            pywikibot.info(f"Processing {mid}")

            page_id = mid.lstrip("M")
            url = f"https://commons.wikimedia.org/w/api.php?action=query&prop=categories&format=json&pageids={page_id}"
            try:
                start = perf_counter()
                pageinfo = generic_http.get(url, follow_redirects=True).json()
                pywikibot.info(f"Fetching {url} took {perf_counter() - start:.4f}s")
            except Exception as e:
                pywikibot.error(f"Failed to fetch {url}: {e}")
                continue

            if "title" not in pageinfo["query"]["pages"][page_id]:
                pywikibot.error(f"Skipping as pageinfo is empty")
                continue

            filename = pageinfo["query"]["pages"][page_id]["title"].lstrip("File:")
            pywikibot.info(f"The filename for {mid} is {filename}")

            categories = [c["title"] for c in pageinfo["query"]["pages"][page_id]["categories"]]
            categories_good = [c.startswith("Category:Flickr images") or c.startswith("Category:Files from Flickr") for c in categories]
            if not any(categories_good):
                pywikibot.error(f"Skipping as it was not categorized into Flickr images. Categories: {categories}")
                continue

            try:
                start = perf_counter()
                claims = backfillr.update_file(filename=filename, mid=mid)
                pywikibot.info(f"Generating {len(claims)} claims took {perf_counter() - start:.4f}s")
            except:
                continue

            if not claims:
                continue

            pywikibot.debug(f"The claims are {claims}")

            payload = {
                "action": "wbeditentity",
                "id": mid,
                "data": json.dumps({"claims": claims}),
                "token": site.get_tokens("csrf")['csrf'],
                "summary": "Update [[Commons:Structured data|SDC]] based on metadata from Flickr. Task #2",
                "tags": "BotSDC",
                "bot": True,
            }
            request = site.simple_request(**payload)

            pprint(DeepDiff([], claims))

            try:
                start = perf_counter()
                request.submit()
                pywikibot.info(f"Update took {perf_counter() - start:.4f}s")
            except Exception as e:
                pywikibot.critical(f"Failed to update: {e}")
                break

            pywikibot.info(f"Successfully updated {mid}")


if __name__ == "__main__":
    main()
