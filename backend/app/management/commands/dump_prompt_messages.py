import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from app.notification_service import load_prompt_messages


def prompt_messages_path():
    return settings.BASE_DIR.parent / 'mobile' / 'src' / 'prompts' / 'messages.json'


class Command(BaseCommand):
    help = (
        'Write the approved message bank (data/REACTprompts.csv) to the JSON '
        'the mobile app bundles, so the app can show a prompt by its prompt_id. '
        'Run with --check to catch a bank edit that never reached the app.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--check',
            action='store_true',
            help='Exit non-zero if the committed app copy differs from the bank.',
        )

    def handle(self, *args, **options):
        path = prompt_messages_path()
        messages = load_prompt_messages()
        payload = json.dumps(messages, indent=2, ensure_ascii=False) + '\n'

        if options['check']:
            if not path.exists():
                raise CommandError(
                    f'{path} does not exist — run "manage.py dump_prompt_messages" and commit it.'
                )
            if path.read_text(encoding='utf-8') != payload:
                raise CommandError(
                    f'{path} is stale. REACTprompts.csv has changed since it was copied to '
                    f'the app. Re-run "manage.py dump_prompt_messages" and ship a new build.'
                )
            self.stdout.write(self.style.SUCCESS(f'{path.name} matches REACTprompts.csv.'))
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(f'Wrote {path} — {len(messages)} messages.'))
