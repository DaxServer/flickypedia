import datetime
import json
import os
import shutil

from authlib.integrations.httpx_client.oauth2_client import OAuth2Client
from flask_login import FlaskLoginClient, current_user
from flickr_photos_api import FlickrPhotosApi
import httpx
import pytest
from pytest import FixtureRequest
import vcr

from flickypedia import create_app
from flickypedia.auth import WikimediaUserSession
from flickypedia.apis.wikimedia import WikimediaApi
from utils import store_user


@pytest.fixture
def user_agent():
    return "Flickypedia/dev (https://commons.wikimedia.org/wiki/Commons:Flickypedia; hello@flickr.org)"


@pytest.fixture(scope="function")
def cassette_name(request: FixtureRequest) -> str:
    """
    Returns the name of a cassette for vcr.py.

    The name can be made up of (up to) three parts:

    -   the name of the test class
    -   the name of the test function
    -   the ID of the test case in @pytest.mark.parametrize

    """
    if request.cls is not None:
        return f"{request.cls.__name__}.{request.node.name}.yml"
    else:
        return f"{request.node.name}.yml"


@pytest.fixture(scope="function")
def vcr_cassette(cassette_name):
    """
    Creates a VCR cassette for use in tests.

    Anything using httpx in this test will record its HTTP interactions
    as "cassettes" using vcr.py, which can be replayed offline
    (e.g. in CI tests).
    """
    with vcr.use_cassette(
        cassette_name,
        cassette_library_dir="tests/fixtures/cassettes",
    ):
        yield


@pytest.fixture(scope="function")
def wikimedia_api(cassette_name):
    """
    Creates an instance of the WikimediaApi class for use in tests.

    This instance of the API will record its interactions as "cassettes"
    using vcr.py, which can be replayed offline (e.g. in CI tests).

    TODO: Document how to record new interactions.
    """
    with vcr.use_cassette(
        cassette_name,
        cassette_library_dir="tests/fixtures/cassettes",
        filter_headers=["authorization"],
    ):
        try:
            token = json.loads(os.environ["WIKIMEDIA_ACCESS_TOKEN"])
            client = OAuth2Client(token=token)
        except KeyError:
            client = httpx.Client()

        yield WikimediaApi(client=client)


@pytest.fixture(scope="function")
def flickr_api(cassette_name, user_agent):
    """
    Creates an instance of the FlickrApi class for use in tests.

    This instance of the API will record its interactions as "cassettes"
    using vcr.py, which can be replayed offline (e.g. in CI tests).
    """
    with vcr.use_cassette(
        cassette_name,
        cassette_library_dir="tests/fixtures/cassettes",
        filter_query_parameters=["api_key"],
    ):
        yield FlickrPhotosApi(
            api_key=os.environ.get("FLICKR_API_KEY", "<REDACTED>"),
            user_agent=user_agent,
        )


@pytest.fixture()
def app(user_agent, tmpdir):
    """
    Creates an instance of the app for use in testing.

    See https://flask.palletsprojects.com/en/3.0.x/testing/#fixtures
    """
    app = create_app(data_directory=tmpdir)
    app.config["TESTING"] = True

    app.config["DUPLICATE_DATABASE_DIRECTORY"] = os.path.join(tmpdir, "duplicates")
    shutil.copyfile(
        "tests/fixtures/duplicates/flickr_ids_from_sdc_for_testing.sqlite",
        os.path.join(
            app.config["DUPLICATE_DATABASE_DIRECTORY"],
            "flickr_ids_from_sdc_for_testing.sqlite",
        ),
    )

    app.config["PHOTOS_PER_PAGE"] = 10

    app.config["USER_AGENT"] = user_agent

    # This means I don't need to pass the CSRF token when posting
    # data to forms, which makes things a bit easier.
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        yield app


@pytest.fixture()
def client(app):
    """
    Creates a client for use in testing.

    See https://flask.palletsprojects.com/en/3.0.x/testing/#fixtures
    """
    with app.test_client() as client:
        yield client


@pytest.fixture
def logged_in_client(app):
    """
    Creates a client for use in testing which is logged in.

    See https://flask-login.readthedocs.io/en/latest/#automated-testing
    """
    app.test_client_class = FlaskLoginClient

    user = WikimediaUserSession(
        id="-1", userid="-1", name="example", encrypted_token=b"<sekrit>"
    )

    # Note: we have to enter the request context before we enter
    # the test client context.  This took me a while to figure
    # out; see https://stackoverflow.com/a/69961887/1558022
    with app.test_request_context():
        with app.test_client(user=user) as client:
            user = store_user(
                token={
                    "token_type": "Bearer",
                    "expires_in": 14400,
                    "access_token": "[ACCESS_TOKEN...abcde]",
                    "refresh_token": "[REFRESH_TOKEN...12345]",
                    "expires_at": datetime.datetime.now().timestamp() + 3600,
                }
            )
            assert current_user == user

            yield client
