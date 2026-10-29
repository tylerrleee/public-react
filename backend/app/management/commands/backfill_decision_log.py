from django.core.management.base import BaseCommand
from django.db import transaction

from app.decision_log import OPEN_EVENT_VIA, link_card_event, record_c0, record_open
from app.models import EMA, EngagementLog, JITAILog


class Command(BaseCommand):
    help = (
        'Fill JITAILog.opened_at/opened_via and c0_helpful/c0_responded_at, and '
        'link resource-card events to their decision, for rows written before '
        'live logging did it. Goes through app/decision_log.py, the same code the '
        'endpoints use, and never overwrites a value already set, so re-running '
        'is a no-op.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would change without writing.')
        parser.add_argument('--user', type=int, default=None,
                            help='Restrict to one user_id.')

    def handle(self, *args, **options):
        user_id = options['user']

        def scoped(queryset):
            return queryset if user_id is None else queryset.filter(user_id=user_id)

        def counts():
            logs = scoped(JITAILog.objects.all())
            return (
                logs.filter(opened_at__isnull=False).count(),
                logs.filter(c0_responded_at__isnull=False).count(),
                scoped(EngagementLog.objects.filter(
                    event_type__startswith='resource_card_shown', jitai_log__isnull=False,
                )).count(),
            )

        before = counts()
        with transaction.atomic():
            for event in scoped(EngagementLog.objects.filter(
                event_type__in=OPEN_EVENT_VIA, jitai_log__isnull=False,
            )):
                record_open(event)
            for ema in scoped(EMA.objects.filter(
                ema_type='prompt_feedback', status='completed', source_jitai_log__isnull=False,
            )).order_by('responded_at'):
                record_c0(ema)
            for event in scoped(EngagementLog.objects.filter(
                event_type__startswith='resource_card_shown', jitai_log__isnull=True,
            )):
                link_card_event(event)
            after = counts()
            if options['dry_run']:
                transaction.set_rollback(True)

        verb = 'would fill' if options['dry_run'] else 'filled'
        self.stdout.write(
            f'{verb} opened_at on {after[0] - before[0]} decisions, C0 on {after[1] - before[1]}, '
            f'and linked {after[2] - before[2]} resource-card events.'
        )
