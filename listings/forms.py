from datetime import datetime, time

from django import forms
from django.conf import settings
from django.utils import timezone

from .models import Listing, PropertyType, Quadrant, Source, Status

FEATURE_CHOICES = [("any", "Any"), ("yes_or_unknown", "Yes or unknown"), ("yes", "Yes")]
PRICE_SLIDER_MAX = 8000  # the slider's top value means "no maximum"
PRICE_SLIDER_STEP = 100
BED_CHOICES = [("", "Any"), ("1", "1+"), ("2", "2+"), ("3", "3+"), ("4", "4+")]
BATH_CHOICES = [("", "Any"), ("1", "1+"), ("1.5", "1.5+"), ("2", "2+"), ("3", "3+")]
PARKING_CHOICES = [("", "Any"), ("1", "1+"), ("2", "2+"), ("3", "3+")]
SORT_CHOICES = [("price", "Price ↑"), ("-price", "Price ↓"), ("newest", "Newest"), ("ppsf", "$/sqft ↑")]


def default_filter_data():
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
        "sort": "price",
    }


class ListingFilterForm(forms.Form):
    # Choices for the filter bar's button rows and slider (read by the template).
    bed_choices = BED_CHOICES
    bath_choices = BATH_CHOICES
    parking_choices = PARKING_CHOICES
    price_slider_max = PRICE_SLIDER_MAX
    price_slider_step = PRICE_SLIDER_STEP

    min_beds = forms.IntegerField(required=False, min_value=0, label="Min beds")
    min_baths = forms.DecimalField(required=False, min_value=0, decimal_places=1, label="Min baths")
    min_parking = forms.IntegerField(required=False, min_value=0, label="Min parking")
    parking_unknown = forms.BooleanField(required=False, label="Include unknown parking")
    min_price = forms.IntegerField(required=False, min_value=0, label="Min price")
    max_price = forms.IntegerField(required=False, min_value=0, label="Max price")
    cities = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple)
    quadrants = forms.MultipleChoiceField(
        required=False, choices=Quadrant.choices, widget=forms.CheckboxSelectMultiple, label="Portland quadrant"
    )
    neighborhood = forms.CharField(required=False)
    sources = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple)
    types = forms.MultipleChoiceField(required=False, choices=PropertyType.choices, widget=forms.CheckboxSelectMultiple)
    statuses = forms.MultipleChoiceField(required=False, choices=Status.choices, widget=forms.CheckboxSelectMultiple)
    wd = forms.ChoiceField(required=False, choices=FEATURE_CHOICES, label="In-unit W/D")
    ac = forms.ChoiceField(required=False, choices=FEATURE_CHOICES, label="AC")
    outdoor = forms.ChoiceField(required=False, choices=FEATURE_CHOICES, label="Outdoor space")
    price_reduced = forms.BooleanField(required=False, label="Price reduced")
    show_inactive = forms.BooleanField(required=False, label="Show off-market")
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


class TrackingForm(forms.ModelForm):
    class Meta:
        model = Listing
        fields = ["status", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 6})}
