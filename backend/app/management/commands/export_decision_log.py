import csv
import io

from django.core.management.base import BaseCommand
from django.db.models import Prefetch

from app.models import EngagementLog, JITAILog
from dashboard.serializers import participant_label

COLUMNS = [
    'decision_point_id', 'participant', 'decision_made_at', 'send_prompt', 'suppression_reason',
    'message_arm', 'prompt_id', 'push_sent_at', 'push_visible', 'opened_at', 'opened_via',
    'c0_helpful', 'c0_responded_at', 'resource_card_shown_n', 'resource_card_shown_at',
]


class Command(BaseCommand):
    help = (
        'Write one CSV row per decision point: what was decided, whether the '
        'prompt was opened and how, the C0 rating and its time, and every time '
        'the resource card was shown. Participants are named by study ID; no '
        'email or message text is exported.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--out', default=None, help='CSV path (default: stdout).')
        parser.add_argument('--sent-only', action='store_true',
                            help='Only decisions where a prompt was sent.')
        parser.add_argument('--limit', type=int, default=None,
                            help='Most recent N decisions only.')

    def handle(self, *args, **options):
        cards = EngagementLog.objects.filter(
            event_type__startswith='resource_card_shown',
        ).order_by('occurred_at')
        logs = (
            JITAILog.objects
            .select_related('user', 'user__wearabledevice')
            .prefetch_related(Prefetch('engagementlog_set', queryset=cards, to_attr='card_events'))
            .order_by('-decision_made_at')
        )
        if options['sent_only']:
            logs = logs.filter(send_prompt=True)
        if options['limit']:
            logs = logs[:options['limit']]

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(COLUMNS)
        for log in logs:
            writer.writerow([
                log.decision_point_id, participant_label(log.user), _iso(log.decision_made_at),
                log.send_prompt, log.suppression_reason, log.message_arm or '', log.prompt_id,
                _iso(log.push_sent_at), log.push_visible, _iso(log.opened_at), log.opened_via,
                log.c0_helpful, _iso(log.c0_responded_at), len(log.card_events),
                ';'.join(_iso(event.occurred_at) for event in log.card_events),
            ])

        if options['out']:
            with open(options['out'], 'w', newline='', encoding='utf-8') as f:
                f.write(buffer.getvalue())
            self.stdout.write(f'Wrote {options["out"]}.')
        else:
            self.stdout.write(buffer.getvalue(), ending='')


def _iso(value):
    return value.isoformat() if value else ''
