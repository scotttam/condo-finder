from datetime import datetime, time

from django import forms
from django.conf import settings
from django.utils import timezone
from django.utils.functional import cached_property

from .models import Listing, PropertyType, Quadrant, SavedQuery, Source, Status

FEATURE_CHOICES = [("any", "Any"), ("yes", "Yes"), ("no", "No"), ("unknown", "Unknown"), ("yes_or_unknown", "Yes or unknown")]
PRICE_SLIDER_MAX = 8000  # the slider's top value means "no maximum"
PRICE_SLIDER_STEP = 100
BED_CHOICES = [("", "Any"), ("1", "1+"), ("2", "2+"), ("3", "3+"), ("4", "4+")]
BATH_CHOICES = [("", "Any"), ("1", "1+"), ("1.5", "1.5+"), ("2", "2+"), ("3", "3+")]
PARKING_CHOICES = [("", "Any"), ("1", "1+"), ("2", "2+"), ("3", "3+")]
# Furnished also keeps the home page's older values: "hide" (no or unknown) and "only" (an alias of yes).
FURNISHED_CHOICES = [*FEATURE_CHOICES, ("hide", "No or unknown"), ("only", "Furnished only")]
VOTE_FILTER_CHOICES = [("any", "Any"), ("everyone_likes", "Everyone 👍"), ("someone_likes", "Someone 👍"),
                       ("disagree", "We disagree"), ("unvoted", "No votes yet")]
SORT_FIELDS = {  # sort key -> label; each sorts both ways ("price" ascending, "-price" descending)
    "price": "Price", "effective": "Effective rent", "ppsf": "$/sqft", "beds": "Beds", "baths": "Baths",
    "sqft": "Sqft", "parking": "Parking", "dom": "Days on market", "drop": "Price drop", "address": "Address",
    "area": "Area", "zip": "ZIP", "type": "Type", "sites": "Sites", "listed": "Listed", "first_seen": "First seen",
    "last_seen": "Last seen", "status": "Status", "votes": "Votes",
}
SORT_CHOICES = [("newest", "Newest")] + [
    choice for key, label in SORT_FIELDS.items() for choice in ((key, f"{label} ↑"), (f"-{key}", f"{label} ↓"))
]
SHORT_FEATURE_MENU = [("any", "Any"), ("yes_or_unknown", "Yes or unknown"), ("yes", "Yes")]
# The home page's drawer keeps its short menus. Search shows every choice.
HOME_MENUS = {
    "wd": SHORT_FEATURE_MENU,
    "ac": SHORT_FEATURE_MENU,
    "outdoor": SHORT_FEATURE_MENU,
    "furnished": [("any", "Any"), ("hide", "Hide furnished"), ("only", "Furnished only")],
    "sort": [("price", "Price ↑"), ("-price", "Price ↓"), ("newest", "Newest"), ("ppsf", "$/sqft ↑")],
}
SEARCH_MENU_FIELDS = ("wd", "ac", "outdoor", "furnished", "parking", "votes")
SEARCH_MENU_SKIP = {"furnished": {"only"}}  # an alias of "yes"
# Filters the home page has no control for. It keeps them as hidden inputs and shows a chip.
SEARCH_ONLY_FIELDS = (
    "q", "max_beds", "max_baths", "max_parking", "min_sqft", "max_sqft", "min_ppsf", "max_ppsf", "min_effective",
    "max_effective", "parking", "min_dom", "max_dom", "new_within", "gone_within", "listed_from", "listed_to",
    "min_drop_amount", "min_drop_percent", "min_price_changes", "price_raised", "zips", "neighborhoods",
    "min_sites", "has_photo", "has_location",
)


class OpenMultipleChoiceField(forms.MultipleChoiceField):
    """A pick list built from the data. A value that's no longer listed still filters, so an old link or
    saved search keeps working."""

    def valid_value(self, value):
        return bool(value) and len(value) <= 100


def app_default_filters():
    """The filters a new group starts from."""
    return {
        "min_beds": "2",
        "min_baths": "2",
        "min_parking": "2",
        "parking_unknown": "on",
        "min_price": str(settings.DEFAULT_MIN_PRICE),
        "max_price": str(settings.DEFAULT_MAX_PRICE),
        "types": [value for value, _ in PropertyType.choices if value != PropertyType.APARTMENT],
        "statuses": [value for value, _ in Status.choices if value != Status.REJECTED],
        "wd": "yes_or_unknown",
        "ac": "yes_or_unknown",
        "outdoor": "yes_or_unknown",
        "furnished": "any",
        "votes": "any",
        "sort": "price",
    }


def default_filter_data(group=None):
    """The group's saved defaults over the app defaults (so a filter added later still has a value)."""
    return {**app_default_filters(), **(group.default_filters if group else {})}


class ListingFilterForm(forms.Form):
    # Choices for the filter bar's button rows and slider (read by the template).
    bed_choices = BED_CHOICES
    bath_choices = BATH_CHOICES
    parking_choices = PARKING_CHOICES
    price_slider_max = PRICE_SLIDER_MAX
    price_slider_step = PRICE_SLIDER_STEP

    q = forms.CharField(required=False, max_length=300, label="Keywords")
    min_beds = forms.IntegerField(required=False, min_value=0, label="Min beds")
    min_baths = forms.DecimalField(required=False, min_value=0, decimal_places=1, label="Min baths")
    min_parking = forms.IntegerField(required=False, min_value=0, label="Min parking")
    parking_unknown = forms.BooleanField(required=False, label="Include unknown parking")
    min_price = forms.IntegerField(required=False, min_value=0, label="Min price")
    max_price = forms.IntegerField(required=False, min_value=0, label="Max price")
    max_beds = forms.IntegerField(required=False, min_value=0, label="Max beds")
    max_baths = forms.DecimalField(required=False, min_value=0, decimal_places=1, label="Max baths")
    max_parking = forms.IntegerField(required=False, min_value=0, label="Max parking")
    min_sqft = forms.IntegerField(required=False, min_value=0, label="Min sqft")
    max_sqft = forms.IntegerField(required=False, min_value=0, label="Max sqft")
    min_ppsf = forms.DecimalField(required=False, min_value=0, decimal_places=2, label="Min $/sqft")
    max_ppsf = forms.DecimalField(required=False, min_value=0, decimal_places=2, label="Max $/sqft")
    min_effective = forms.IntegerField(required=False, min_value=0, label="Min effective rent")
    max_effective = forms.IntegerField(required=False, min_value=0, label="Max effective rent")
    cities = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple)
    quadrants = forms.MultipleChoiceField(
        required=False, choices=Quadrant.choices, widget=forms.CheckboxSelectMultiple, label="Portland quadrant"
    )
    neighborhood = forms.CharField(required=False)
    zips = OpenMultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple, label="ZIP codes")
    neighborhoods = OpenMultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple, label="Neighborhoods")
    min_sites = forms.IntegerField(required=False, min_value=1, label="Listed on at least (sites)")
    has_photo = forms.BooleanField(required=False, label="Has a photo")
    has_location = forms.BooleanField(required=False, label="On the map")
    sources = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple)
    types = forms.MultipleChoiceField(required=False, choices=PropertyType.choices, widget=forms.CheckboxSelectMultiple)
    statuses = forms.MultipleChoiceField(required=False, choices=Status.choices, widget=forms.CheckboxSelectMultiple)
    votes = forms.ChoiceField(required=False, choices=VOTE_FILTER_CHOICES, label="Votes")
    wd = forms.ChoiceField(required=False, choices=FEATURE_CHOICES, label="In-unit W/D")
    ac = forms.ChoiceField(required=False, choices=FEATURE_CHOICES, label="AC")
    outdoor = forms.ChoiceField(required=False, choices=FEATURE_CHOICES, label="Outdoor space")
    furnished = forms.ChoiceField(required=False, choices=FURNISHED_CHOICES, label="Furnished")
    parking = forms.ChoiceField(required=False, choices=FEATURE_CHOICES, label="Has parking")
    price_reduced = forms.BooleanField(required=False, label="Price reduced")
    min_drop_amount = forms.IntegerField(required=False, min_value=1, label="Dropped at least ($)")
    min_drop_percent = forms.IntegerField(required=False, min_value=1, max_value=99, label="Dropped at least (%)")
    min_price_changes = forms.IntegerField(required=False, min_value=1, label="Price changes at least")
    price_raised = forms.BooleanField(required=False, label="Price went up")
    specials = forms.BooleanField(required=False, label="Move-in specials only")
    show_inactive = forms.BooleanField(required=False, label="Show off-market")
    min_dom = forms.IntegerField(required=False, min_value=0, label="Min days on market")
    max_dom = forms.IntegerField(required=False, min_value=0, label="Max days on market")
    new_within = forms.IntegerField(required=False, min_value=1, label="New in the last (days)")
    gone_within = forms.IntegerField(required=False, min_value=1, label="Off-market in the last (days)")
    listed_from = forms.DateField(required=False, label="Listed from")
    listed_to = forms.DateField(required=False, label="Listed to")
    sort = forms.ChoiceField(required=False, choices=SORT_CHOICES)
    # "Search this area": the map's visible bounds, set by the map script.
    north = forms.FloatField(required=False, widget=forms.HiddenInput)
    south = forms.FloatField(required=False, widget=forms.HiddenInput)
    east = forms.FloatField(required=False, widget=forms.HiddenInput)
    west = forms.FloatField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cities"].choices = [(city, city) for city in settings.TARGET_CITIES]
        self.fields["sources"].choices = list(Source.objects.order_by("name").values_list("key", "name"))
        active = Listing.objects.filter(is_active=True)
        for name, column in (("zips", "zip_code"), ("neighborhoods", "neighborhood")):
            values = set(active.exclude(**{column: ""}).values_list(column, flat=True).distinct())
            values |= {value for value in self.raw_values(name) if value}
            self.fields[name].choices = [(value, value) for value in sorted(values)]

    def raw_values(self, name):
        """The submitted values for a field as a list of strings (the data may be a QueryDict or a dict)."""
        if not self.is_bound:
            return []
        if hasattr(self.data, "getlist"):
            return self.data.getlist(name)
        value = self.data.get(name)
        if value in (None, ""):
            return []
        return [str(v) for v in value] if isinstance(value, (list, tuple)) else [str(value)]

    def search_only_values(self):
        """(name, value) for each Search-only filter in this form's data, for the home page's hidden inputs."""
        return [(name, value) for name in SEARCH_ONLY_FIELDS for value in self.raw_values(name) if value not in ("", "any")]

    def active_count(self):
        """How many filters are set (Search's "Filters (n)"). Sort isn't a filter; the map area counts once."""
        data = getattr(self, "cleaned_data", {})
        area = ("north", "south", "east", "west")
        count = sum(1 for name, value in data.items()
                    if name not in ("sort", *area) and value not in (None, "", [], False, "any"))
        return count + all(data.get(side) is not None for side in area)

    def _menu(self, name, choices):
        """Options for a select. A value from elsewhere (a Search link on the home page, say) is added, so the
        menu shows it and the next change doesn't drop it."""
        current = str(self[name].value() or "")
        if current and current not in dict(choices):
            choices = [*choices, (current, dict(self.fields[name].choices).get(current, current))]
        return [{"value": value, "label": label, "selected": value == current} for value, label in choices]

    @cached_property
    def home_menus(self):
        return {name: self._menu(name, choices) for name, choices in HOME_MENUS.items()}

    @cached_property
    def search_menus(self):
        menus = {
            name: self._menu(name, [(v, label) for v, label in self.fields[name].choices if v not in SEARCH_MENU_SKIP.get(name, ())])
            for name in SEARCH_MENU_FIELDS
        }
        menus["sort"] = self._menu("sort", [("", "Best match"), *SORT_CHOICES])
        return menus


HISTORY_EVENTS = ["Listed for rent", "Price change", "Listing removed", "Asked the landlord", "Note"]


class PriceEntryForm(forms.Form):
    """A price-history entry added or corrected on the listing page."""

    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    price = forms.IntegerField(min_value=1)
    event = forms.CharField(max_length=40, required=False)

    @classmethod
    def for_change(cls, change):
        return cls(initial={"date": timezone.localdate(change.seen_at), "price": change.price, "event": change.event})

    def seen_at(self):
        day = self.cleaned_data["date"]
        return timezone.make_aware(datetime.combine(day, time(12)))


class SavedQueryForm(forms.ModelForm):
    class Meta:
        model = SavedQuery
        fields = ["name", "sql"]
