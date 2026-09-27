from .appfolio import AppFolioScraper
from .nesthub import NesthubScraper
from .redfin import RedfinScraper
from .zillow import ZillowScraper

PLATFORMS = {"appfolio": AppFolioScraper, "nesthub": NesthubScraper, "redfin": RedfinScraper, "zillow": ZillowScraper}

# To add a property manager, append one entry. AppFolio needs its <subdomain>.appfolio.com;
# Nesthub needs the site's listings page URL.
SOURCES = [
    {"key": "pearl", "name": "Pearl Property Management", "platform": "appfolio", "subdomain": "pearlpropertymanagement"},
    {"key": "living-room", "name": "Living Room Realty", "platform": "appfolio", "subdomain": "livingroomproperty"},
    {"key": "tmg", "name": "The Management Group", "platform": "appfolio", "subdomain": "tmgoregon"},
    {"key": "mainlander", "name": "Mainlander", "platform": "appfolio", "subdomain": "mainlander"},
    {"key": "propm", "name": "PropM (AppFolio)", "platform": "appfolio", "subdomain": "propmhomes"},
    {"key": "utopia", "name": "Utopia Management", "platform": "appfolio", "subdomain": "utopiamanagement"},
    {"key": "uptown", "name": "Uptown Properties", "platform": "nesthub", "list_url": "https://www.uptownpm.com/portland-homes-for-rent"},
    {"key": "propm-site", "name": "PropM (website)", "platform": "nesthub", "list_url": "https://www.propmhomes.com/portland-homes-for-rent"},
    # Redfin city region ids: Portland 30772, Lake Oswego 30777, Beaverton 1432.
    {"key": "redfin", "name": "Redfin", "platform": "redfin", "region_ids": [30772, 30777, 1432], "request_delay": 2},
    {"key": "zillow", "name": "Zillow", "platform": "zillow", "city_slugs": ["portland-or", "lake-oswego-or", "beaverton-or"],
     "request_delay": 3, "max_detail_fetches": 40},
]


def build_scraper(config, fetcher=None):
    options = {k: v for k, v in config.items() if k not in ("key", "name", "platform")}
    return PLATFORMS[config["platform"]](key=config["key"], name=config["name"], fetcher=fetcher, **options)
