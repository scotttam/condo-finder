from django import forms
from django.conf import settings

from .models import Listing, PropertyType, Source, Status

FEATURE_CHOICES = [("any", "Any"), ("yes_or_unknown", "Yes or unknown"), ("yes", "Yes")]
SORT_CHOICES = [("price", "Price ↑"), ("-price", "Price ↓"), ("newest", "Newest"), ("ppsf", "$/sqft ↑")]


def default_filter_data():
    return {
        "min_beds": "2",
        "min_baths": "2",
        "min_parking": "2",
        "parking_unknown": "on",
        "max_price": str(settings.DEFAULT_MAX_PRICE),
        "types": [value for value, _ in PropertyType.choices if value != PropertyType.APARTMENT],
        "statuses": [value for value, _ in Status.choices if value != Status.REJECTED],
        "wd": "yes_or_unknown",
        "ac": "yes_or_unknown",
        "outdoor": "yes_or_unknown",
        "sort": "price",
    }


class ListingFilterForm(forms.Form):
    min_beds = forms.IntegerField(required=False, min_value=0, label="Min beds")
    min_baths = forms.DecimalField(required=False, min_value=0, decimal_places=1, label="Min baths")
    min_parking = forms.IntegerField(required=False, min_value=0, label="Min parking")
    parking_unknown = forms.BooleanField(required=False, label="Include unknown parking")
    max_price = forms.IntegerField(required=False, min_value=0, label="Max price")
    cities = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple)
    neighborhood = forms.CharField(required=False)
    sources = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple)
    types = forms.MultipleChoiceField(required=False, choices=PropertyType.choices, widget=forms.CheckboxSelectMultiple)
    statuses = forms.MultipleChoiceField(required=False, choices=Status.choices, widget=forms.CheckboxSelectMultiple)
    wd = forms.ChoiceField(required=False, choices=FEATURE_CHOICES, label="In-unit W/D")
    ac = forms.ChoiceField(required=False, choices=FEATURE_CHOICES, label="AC")
    outdoor = forms.ChoiceField(required=False, choices=FEATURE_CHOICES, label="Outdoor space")
    show_inactive = forms.BooleanField(required=False, label="Show off-market")
    sort = forms.ChoiceField(required=False, choices=SORT_CHOICES)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cities"].choices = [(city, city) for city in settings.TARGET_CITIES]
        self.fields["sources"].choices = list(Source.objects.order_by("name").values_list("key", "name"))


class TrackingForm(forms.ModelForm):
    class Meta:
        model = Listing
        fields = ["status", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 6})}
