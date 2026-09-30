import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from accounts.groups import move_to_group, owners_group
from accounts.models import Profile


class Command(BaseCommand):
    help = "Create or update the site admin's account (staff) in the owners' group."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--name", required=True, help="Display name shown on comments, votes and the Feed.")
        parser.add_argument("--password", help="Asked for when creating an account and this is omitted.")

    def handle(self, *args, email, name, password=None, **options):
        email, name = email.strip().lower(), name.strip()[:60]
        User = get_user_model()
        user = User.objects.filter(Q(username__iexact=email) | Q(email__iexact=email)).first()
        created = user is None
        if created:
            user = User(username=email)
            password = password or self._ask_password()
        user.username = user.email = email
        user.is_staff = user.is_superuser = True
        if password:
            user.set_password(password)
        user.save()

        group = owners_group()
        profile = Profile.objects.filter(user=user).first()
        if profile is None:
            profile = Profile.objects.create(user=user, group=group, display_name=name)
        else:
            profile = move_to_group(user, group)
            profile.display_name = name
            profile.save(update_fields=["display_name"])
        self.stdout.write(f'{"Created" if created else "Updated"} {email} ({name}) in "{group.name}".')

    def _ask_password(self):
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Password again: "):
            raise CommandError("The passwords do not match.")
        try:
            validate_password(password)
        except ValidationError as error:
            raise CommandError(" ".join(error.messages))
        return password
