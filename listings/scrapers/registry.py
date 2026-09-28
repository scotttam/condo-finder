from .appfolio import AppFolioScraper
from .craigslist import CraigslistScraper
from .nesthub import NesthubScraper
from .redfin import RedfinScraper
from .rentengine import RentEngineScraper
from .zillow import ZillowScraper

PLATFORMS = {
    "appfolio": AppFolioScraper,
    "nesthub": NesthubScraper,
    "redfin": RedfinScraper,
    "zillow": ZillowScraper,
    "craigslist": CraigslistScraper,
    "rentengine": RentEngineScraper,
}

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
    # RentEngine: `slug` is the company's embed name (rentengine.io/c/<slug>); loaded in headless Chromium.
    {"key": "chroma", "name": "Chroma Property Management", "platform": "rentengine", "slug": "chromapm",
     "request_delay": 2, "max_detail_fetches": 30},
    # Redfin city region ids: Portland 30772, Lake Oswego 30777, Beaverton 1432.
    {"key": "redfin", "name": "Redfin", "platform": "redfin", "region_ids": [30772, 30777, 1432],
     # Listing pages are behind AWS bot protection that blocks fast fetching: go slowly, and only
     # for listings Zillow doesn't also cover (Zillow's page already gives their history/details).
     "request_delay": 20, "max_detail_fetches": 10, "skip_details_if_on": "zillow"},
    {"key": "zillow", "name": "Zillow", "platform": "zillow", "city_slugs": ["portland-or", "lake-oswego-or", "beaverton-or"],
     "request_delay": 3, "max_detail_fetches": 80},
    {"key": "craigslist", "name": "Craigslist", "platform": "craigslist",
     "search_url": "https://www.craigslist.org/search/area/portland?cat=apa&min_bedrooms=2&min_bathrooms=2",
     "request_delay": 2, "max_detail_fetches": 60},
]


def build_scraper(config, fetcher=None):
    options = {k: v for k, v in config.items() if k not in ("key", "name", "platform")}
    return PLATFORMS[config["platform"]](key=config["key"], name=config["name"], fetcher=fetcher, **options)
