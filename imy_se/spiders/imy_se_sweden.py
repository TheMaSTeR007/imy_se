from urllib.parse import urlparse, urlunparse, parse_qs, quote, urlencode
from scrapy.cmdline import execute
from unicodedata import normalize
from lxml.html import fromstring
from datetime import datetime
from typing import Iterable
from scrapy import Request
from html import unescape
import pandas as pd
import random
import scrapy
import json
import time
import evpn
import os
import re


def encode_url(url):
    """Encodes the query parameters of a URL, ensuring spaces are replaced with %20."""
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    # Manually encode query parameters with %20 for spaces
    encoded_query = "&".join(f"{quote(key)}={quote(value[0])}" for key, value in query_params.items())
    # Rebuild the URL
    encoded_url = urlunparse((parsed_url.scheme, parsed_url.netloc, parsed_url.path, parsed_url.params, encoded_query, parsed_url.fragment))
    return encoded_url


def clean_text(raw_string):
    """Cleans a raw string by removing special characters, normalizing Unicode,
    unescaping HTML entities, and collapsing whitespace."""
    unescaped_string = unescape(raw_string)  # Step 1: HTML unescape
    normalized_string = normalize('NFKC', unescaped_string)  # Step 2: normalize Unicode
    # Matches \xa0, \r, \n, and other unwanted characters
    cleaned_string = re.sub(pattern=r'[\xa0\r\n]+', repl=' ', string=normalized_string)  # Step 3: Remove unwanted characters using regex
    cleaned_string = re.sub(pattern=r'\s+', repl=' ', string=cleaned_string).strip()  # Step 4: Collapse multiple spaces into one and trim
    return cleaned_string


def extract_and_format_date(input_text):
    """Extracts a date in 'DD Month YYYY' format from a string and converts it into 'YYYY-MM-DD' format."""
    # Regex to match 'DD Month YYYY'
    date_match = re.search(pattern=r'(\d{1,2}) (\w+) (\d{4})', string=input_text)
    if date_match:
        day, month, year = date_match.groups()
        try:
            # Convert to datetime object and then to desired format
            date_obj = datetime.strptime(f"{day} {month} {year}", "%d %B %Y")
            return date_obj.strftime("%Y-%m-%d")
        except ValueError:
            return 'N/A'  # Return None if date parsing fails
    return 'N/A'  # Return None if no date is found


def get_news_heading(news_container_div) -> str:
    news_heading = ' '.join(news_container_div.xpath('./div[contains(@class, "imy-newspage__heading-container")]//h1[contains(@class, "imy-newspage__heading")]/text()')).strip()
    return news_heading if news_heading != '' else 'N/A'


def get_published_date(news_container_div) -> str:
    published_date = ' '.join(news_container_div.xpath('./div[contains(@class, "imy-newspage__published")]/text()')).strip()
    published_date = extract_and_format_date(published_date)
    return published_date if published_date != '' else 'N/A'


# def get_description(news_container_div):
#     description = ' '.join(
#         news_container_div.xpath(
#             './div[contains(@class, "imy-newspage__preamble")]//text() | ./div[contains(@class, "imy-newspage__content")]//p[not(strong or a) and not(contains(text(), "+")) and not(contains(text(), "For further information, please contact"))]//text()')).strip()
#     # importrant xpath
#     # //div[contains(@class, "imy-newspage__content-container")]/./div[contains(@class, "imy-newspage__preamble")]//text() | //div[contains(@class, "imy-newspage__content-container")]//div[contains(@class, "imy-newspage__content")]//p[not(strong)]
#     return clean_text(description) if description != '' else 'N/A'


def get_description(news_container_div):
    # Extract text from the preamble and content, including sibling heading tags of selected <p> tags
    description = ' '.join(
        news_container_div.xpath(
            '''
            ./div[contains(@class, "imy-newspage__preamble")]//text() | 
            ./div[contains(@class, "imy-newspage__content")]
            //p[not(strong or a) and not(contains(text(), "+")) and not(contains(text(), "For further information, please contact"))]//text() |
            ./div[contains(@class, "imy-newspage__content")]
            //p[not(strong or a) and not(contains(text(), "+")) and not(contains(text(), "For further information, please contact"))]
            /following-sibling::h2[1]//text() | 
            ./div[contains(@class, "imy-newspage__content")]//h2/text() | 
            //div[contains(@class, "imy-newspage__content")]/section/h4//text()
            '''
        )).strip()

    return clean_text(description) if description != '' else 'N/A'


def get_latest_update(news_container_div):
    latest_update = ' '.join(news_container_div.xpath('.//div[contains(@class, "imy-contentpage__date-container")]//text()'))
    latest_update = extract_and_format_date(latest_update)
    return latest_update if latest_update != '' else 'N/A'


def get_tag_name(news_container_div):
    tag_name = ' | '.join(news_container_div.xpath('.//div[contains(@class, "imy-contentpage__label-container")]/a/text()')).strip().replace(',', '')
    return tag_name if tag_name != '' else 'N/A'


def get_tag_url(news_container_div):
    tag_urls_list = news_container_div.xpath('.//div[contains(@class, "imy-contentpage__label-container")]/a/@href')
    tag_url = ' | '.join([encode_url('https://www.imy.se' + tag_url_slug) for tag_url_slug in tag_urls_list]).strip()
    return tag_url if tag_url != '' else 'N/A'


def get_pdf_url(news_container_div):
    pdf_urls_list = news_container_div.xpath('./div[contains(@class, "imy-newspage__content")]/p/a[contains(@href, ".pdf")]/@href')
    pdf_url = ' | '.join('https://www.imy.se' + pdf_url_slug for pdf_url_slug in pdf_urls_list)
    return pdf_url if pdf_url != '' else 'N/A'


def get_contact_details(news_container_div):
    contact_details = news_container_div.xpath('./div[contains(@class, "imy-newspage__content")]//p[contains(normalize-space(), "phone") or contains(normalize-space(), "telephone") or contains(normalize-space(), "+")]//text()')

    # Regex for extracting name and phone number
    contact_regex = re.compile(r"(?P<name>.*?)(?:,|\s-\s)?(?:telephone|phone)?\s*(?P<number>\+[\d\s-]+)")

    contact_name_list = []
    contact_telephone_list = []

    for contact_text in contact_details:
        match = contact_regex.search(contact_text.strip())
        if match:
            contact_name = match.group('name').replace(',', '').replace(':', '').strip()
            contact_number = match.group('number').replace(',', '').replace(':', '').strip()
            contact_name_list.append(contact_name)
            contact_telephone_list.append(contact_number)

    contact_dict = {
        'contact_name': ' | '.join(contact_name_list) if contact_name_list else 'N/A',
        'contact_telephone': ' | '.join(contact_telephone_list) if contact_telephone_list else 'N/A'
    }
    return contact_dict


class ImySeSwedenSpider(scrapy.Spider):
    name = "imy_se_sweden"

    def __init__(self):
        self.start = time.time()
        super().__init__()
        print('Connecting to VPN (SWEDEN)')
        self.api = evpn.ExpressVpnApi()  # Connecting to VPN (SWEDEN)
        self.api.connect(country_id='23')  # SWEDEN country code for vpn
        time.sleep(10)  # keep some time delay before starting scraping because connecting
        print('VPN Connected!' if self.api.is_connected else 'VPN Not Connected!')

        # self.delivery_date = datetime.now().strftime('%Y%m%d')
        self.final_data_list = list()  # List of data to make DataFrame then Excel

        # Path to store the Excel file can be customized by the user
        self.excel_path = r"../Excel_Files"  # Client can customize their Excel file path here (default: govtsites > govtsites > Excel_Files)
        os.makedirs(self.excel_path, exist_ok=True)  # Create Folder if not exists
        self.filename = fr"{self.excel_path}/{self.name}.xlsx"  # Filename with Scrape Date

        self.browsers = ["chrome110", "edge99", "safari15_5"]

        self.headers = {
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
            'DNT': '1',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
        }

    def start_requests(self) -> Iterable[Request]:
        query_params = {
            'query': 'fined',
            'selectedSection': '',
            'pageSize': '10',
            'page': '1',
            'pageId': '1832',
        }
        url = 'https://www.imy.se/en/api/search/listsearch?' + urlencode(query_params)
        # Sending request on an api which gives news detail page's url in html text in response json.
        yield scrapy.Request(url=url, headers=self.headers, method='GET', callback=self.parse,
                             meta={'impersonate': random.choice(self.browsers)}, dont_filter=True, cb_kwargs={'query_params': query_params})

    def parse(self, response, **kwargs):
        query_params = kwargs['query_params']
        json_dict = json.loads(response.text)

        news_dicts_list = json_dict.get('hits', [])
        for news_dict in news_dicts_list:
            news_detail_url = news_dict.get('url', 'N/A')
            # Send request on detail page url
            yield scrapy.Request(url=news_detail_url, headers=self.headers, method='GET', callback=self.detail_parse,
                                 meta={'impersonate': random.choice(self.browsers)}, dont_filter=True,
                                 cb_kwargs={'url': f'https://www.imy.se/en/news/?query=fined&page={query_params['page']}', 'news_detail_url': news_detail_url})

        # Handle Pagination
        if int(query_params['page']) < json_dict['numberOfPages']:
            # Increment the page number
            query_params['page'] = str(int(query_params['page']) + 1)

            # Construct the next page URL
            next_page_url = 'https://www.imy.se/en/api/search/listsearch?' + urlencode(query_params)

            # Send a request for the next page
            yield scrapy.Request(url=next_page_url, headers=self.headers, method='GET', callback=self.parse,
                                 meta={'impersonate': random.choice(self.browsers)}, dont_filter=True, cb_kwargs={'query_params': query_params})

    def detail_parse(self, response, **kwargs):
        parsed_tree = fromstring(response.text)
        news_container_div = parsed_tree.xpath('//div[contains(@class, "imy-newspage__content-container")]')[0]

        data_dict = dict()
        data_dict['url'] = kwargs['url']
        data_dict['news_detail_url'] = kwargs['news_detail_url']
        data_dict['news_heading'] = get_news_heading(news_container_div)
        data_dict['published_date'] = get_published_date(news_container_div)
        data_dict['description'] = get_description(news_container_div)
        data_dict['latest_update'] = get_latest_update(news_container_div)
        data_dict['tag_name'] = get_tag_name(news_container_div)
        data_dict['tag_url'] = get_tag_url(news_container_div)
        data_dict['pdf_url'] = get_pdf_url(news_container_div)
        contact_details = get_contact_details(news_container_div)
        data_dict['contact_name'] = contact_details['contact_name']
        data_dict['contact_telephone'] = contact_details['contact_telephone']
        # print(data_dict)
        self.final_data_list.append(data_dict)

    def close(self, reason):
        print("Converting List of Dictionaries into DataFrame, then into Excel file...")
        if self.final_data_list:
            try:
                print("Creating Native sheet...")
                data_df = pd.DataFrame(self.final_data_list)
                with pd.ExcelWriter(path=self.filename, engine='xlsxwriter', engine_kwargs={"options": {'strings_to_urls': False}}) as writer:
                    data_df.insert(loc=0, column='id', value=range(1, len(data_df) + 1))  # Add 'id' column at position 1
                    data_df.to_excel(excel_writer=writer, index=False)
                print("Native Excel file Successfully created.")
            except Exception as e:
                print('Error while Generating Native Excel file:', e)
        else:
            print('Final-Data-List is empty, Hence not generating Excel File.')
        if self.api.is_connected:  # Disconnecting VPN if it's still connected
            self.api.disconnect()
        end = time.time()
        print(f'Scraping done in {end - self.start} seconds.')


if __name__ == '__main__':
    execute(f'scrapy crawl {ImySeSwedenSpider.name}'.split())
