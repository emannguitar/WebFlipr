import threading
import time
import requests
from selenium import webdriver


from .interfaces import GooglePlacesInterface, DatabaseInterface
from .lat_long_generator import LatLongGenerator

options = webdriver.ChromeOptions()
options.add_argument("--window-size=1920,1080")
options.add_argument("--headless")


class PlacesScraper:
    def __init__(self, lat_long_generator: LatLongGenerator, places_interface_config: dict, database_config: dict, imgur_host_config:dict, min_doc_count: int, autostart=True):
        self.lat_long_generator = lat_long_generator
        self.places_interface = GooglePlacesInterface(**places_interface_config)
        self.database = DatabaseInterface(**database_config)
        self.imgur_host_config = imgur_host_config
        self.min_doc_count = min_doc_count
        self.running = autostart
        self.watcher_thread = threading.Thread(target=self.doc_count_watcher).start()

    def enable(self):
        """Enable database watcher"""
        self.running = True

    def disable(self):
        """Disable database watcher"""
        self.running = False

    def places_website_in_archive(self, place: dict):
        """Returns True if the place's website is in the archive database, False otherwise"""
        if not place.get('website'):
            return False  # For now, places without a website are ignored.
        base_site = place['website'][8:].split('/')[0]
        database_search = self.database.collection_archive.find({'website': {'$regex': base_site}}, limit=2)
        return not bool(database_search.count())

    def doc_count_watcher(self):
        """Checks the size of the database and if there are less items than the specified minimum, performs and processes
            A new search until the database has reached the minimum size."""
        while True:
            if self.running:
                while self.database.count < self.min_doc_count:
                    coords = self.lat_long_generator.next_coords()
                    print(f'Doc count ({self.database.count}) less than minimum ({self.min_doc_count}). Searching at {coords}')
                    new_items = self.places_interface.filtered_search(coords)
                    print(f'Search returned {len(new_items)} results')
                    filtered_items = list(filter(self.places_website_in_archive, new_items))
                    print(f'After filtering, {len(filtered_items)} remain')
                    print('Adding screenshot links')
                    self.add_screenshot_links(filtered_items)
                    print('Adding to database')
                    self.database.add(filtered_items)
            time.sleep(2)

    def add_screenshot_links(self, business_info_dicts):
        """Takes a list of dicts representing a businesses information and takes a screenshot of their website, uploads
            to imgur, and adds the link to the dict for each dict in the list."""
        selenium_browser = webdriver.Chrome(options=options)
        total = len(business_info_dicts)
        ct = 0
        for business_info_dict in business_info_dicts:
            ct += 1
            print(f'---Processing {ct}/{total}---')
            url = business_info_dict.get('website', 'https://www.google.com')
            print(f'Loading URL [{url}]')
            try:
                selenium_browser.get(url)
            except Exception as e:
                print('Exception while loading url: ', e)
            print('Taking screenshot')
            image_bytes = selenium_browser.get_screenshot_as_png()
            print('Uploading to imgur')
            r = requests.post(
                'https://api.imgur.com/3/upload',
                data={'image': image_bytes},
                headers={'Authorization': f'Client-ID {self.imgur_host_config["client_id"]}'}
            )
            if r.ok:
                business_info_dict['screenshot_url'] = r.json()['data']['link']
            else:
                print(r)
        selenium_browser.quit()
