"""
Methods for dealing with categories on Wikimedia Commons.
"""

import re

from .base import WikimediaApiBase


class CategoryMethods(WikimediaApiBase):
    def find_pd_us_templates(self) -> list[str]:
        """
        Return a list of pages that are members of this category.
        """
        json = self._get_json(
            params={
                "action": "query",
                "list": "categorymembers",
                "cmtitle": "Category:PD-USGov license tags",
                "cmlimit": 500,
                "cmnamespace": 10,
            },
        )

        # The JSON response is of the form:
        #     {
        #         "batchcomplete": "",
        #         "query": {
        #             "categorymembers": [
        #                 {
        #                     "pageid": 250,
        #                     "ns": 10,
        #                     "title": "Template:PD-USGov"
        #                 }
        #             ]
        #         }
        #     }

        return [re.sub(r"^Template:", "", member['title']) for member in json["query"]["categorymembers"]]

    def find_matching_categories(self, query: str) -> list[str]:
        """
        Return a list of categories that might match this query.

        This can be used to build an autocomplete interface for categories,
        e.g. if the user types "a" we can suggest categories that
        include the letter "a":

                >>> find_matching_categories(query='a')
                ['A',
                'Aircraft of Uzbekistan',
                'Aircraft of Malawi',
                'Aircraft in Portugal',
                'Aircraft in Sierra Leone',
                'Aircraft in Malawi',
                'Architectural elements in Russia',
                'Aircraft in Thailand',
                'Airliners in Russian service',
                'Airliners in Malawian service']

        Note: the results from this API may vary over time, or even
        different requests. For example, there is a test in test_wikimedia.py
        that makes the same query as the example, but returns a slightly
        different set of categories.
        """
        # I found this API action by observing the network traffic in
        # the Upload Wizard.
        #
        # I changed the response format from JSON to XML to give better
        # visibility into the structure of the response -- the JSON
        # gives an opaque list of lists.
        #
        # See https://www.mediawiki.org/wiki/API:Opensearch
        xml = self._get_xml(
            params={
                "action": "opensearch",
                "limit": "10",
                "search": query,
                # Here "14" is the namespace for categories; see
                # https://commons.wikimedia.org/wiki/Help:Namespaces
                "namespace": "14",
            },
        )

        # The XML response is of the form:
        #
        #   <?xml version="1.0"?>
        #   <SearchSuggestion xmlns="http://opensearch.org/searchsuggest2" version="2.0">
        #     <Query xml:space="preserve">a</Query>
        #     <Section>
        #       <Item>
        #         <Text xml:space="preserve">Category:A</Text>
        #         <Url xml:space="preserve">https://commons.wikimedia.org/wiki/Category:A</Url>
        #         <Image source="https://upload.wikimedia.org/wikipedia/commons/thumb/8/85/ICS_Alfa.svg/50px-ICS_Alfa.svg.png" width="50" height="50"/>
        #       </Item>
        #       …
        #
        # We're interested in those <Text> values.
        namespaces = {"": "http://opensearch.org/searchsuggest2"}

        return [
            re.sub(r"^Category:", "", text_elem.text)  # type: ignore
            for text_elem in xml.findall(".//Text", namespaces=namespaces)
        ]
