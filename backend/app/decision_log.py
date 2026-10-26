"""Copy what happened after a decision onto its JITAILog row.

The raw events stay where they are (EngagementLog, EMA). These helpers only
denormalize them onto the decision row, or link them to it, so one row per
decision_point_id carries the open time, the C0 rating and the resource-card
displays. The live endpoints and `manage.py backfill_decision_log` both go
through here, so a backfill produces exactly what live logging would have.
"""

from django.db.models import Q

from app.models import EngagementLog, JITAILog

OPEN_EVENT_VIA = {
    'notification_tapped': 'notification_tap',
    'prompt_message_shown': 'in_app',
}
C0_HELPFUL_SUB_ITEM = 'C0_helpful'


def record_open(event) -> None:
    # The earliest open wins, so a tap followed by the message rendering is
    # recorded as a tap, whatever order the two requests arrive in.
    via = OPEN_EVENT_VIA.get(event.event_type)
    if via is None or event.jitai_log_id is None:
        return
    (
        JITAILog.objects
        .filter(pk=event.jitai_log_id, user_id=event.user_id, send_prompt=True)
        .filter(Q(opened_at__isnull=True) | Q(opened_at__gt=event.occurred_at))
        .update(opened_at=event.occurred_at, opened_via=via)
    )


def record_c0(ema) -> None:
    # A dismissed C0 has no rating, so the decision row keeps blank C0 fields.
    if ema.ema_type != 'prompt_feedback' or ema.source_jitai_log_id is None or ema.status != 'completed':
        return
    helpful = (
        ema.item_responses
        .filter(sub_item_id=C0_HELPFUL_SUB_ITEM)
        .values_list('value_choice', flat=True)
        .first()
    )
    if not helpful:
        return
    (
        JITAILog.objects
        .filter(pk=ema.source_jitai_log_id, c0_responded_at__isnull=True)
        .update(c0_helpful=helpful, c0_responded_at=ema.responded_at)
    )


def link_card_event(event) -> None:
    # A card after a check-in belongs to the decision made on that check-in. A
    # home-screen card has no check-in, so it is tied to the participant's most
    # recent decision at or before it was shown.
    if event.jitai_log_id is not None:
        return
    if event.event_type == 'resource_card_shown_checkin' and event.ema_id is not None:
        decision = JITAILog.objects.filter(ema_id=event.ema_id).order_by('decision_made_at').first()
    elif event.event_type == 'resource_card_shown_home':
        decision = (
            JITAILog.objects
            .filter(user_id=event.user_id, decision_made_at__lte=event.occurred_at)
            .order_by('-decision_made_at')
            .first()
        )
    else:
        return
    if decision is not None:
        EngagementLog.objects.filter(pk=event.pk).update(jitai_log=decision)
        event.jitai_log = decision


def link_checkin_cards_to(decision) -> None:
    # The decision row is written by Celery up to a few minutes after the
    # check-in, usually after the card event has already arrived.
    if decision.ema_id is None:
        return
    (
        EngagementLog.objects
        .filter(ema_id=decision.ema_id, event_type='resource_card_shown_checkin', jitai_log__isnull=True)
        .update(jitai_log=decision)
    )


def apply_engagement(event) -> None:
    record_open(event)
    link_card_event(event)
