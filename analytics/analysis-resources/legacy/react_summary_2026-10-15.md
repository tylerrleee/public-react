# REACT study summary, Sep 29 to Oct 15, 2026

Phase 1 cohort: 5 RS participants (test and unlabelled accounts excluded). 

- Eastern days 2026-09-29 to 2026-10-15 (17 days). 
- Read from the production database 2026-10-16. 
- Check-in completion uses daily metrics computed 2026-10-16.
- n = 5 participants enrolled ('RS___').

## Overall

| Measure | To date |
| :--- | :--- |
| Check-ins completed / delivered | 226/438 (52%) |
| Decision points evaluated | 251 |
| Eligible (available) decision points | 33 of 251; MRT days 33/154 (21% vs 21% planned) |
| Suppressed by a safeguard | 16 (run-in period 16) |
| Prompts sent | 19 |
| Prompts seen (receipt or rating) | 1 of 19; device receipts 0 |
| Helpfulness ratings (Yes / Somewhat / No) | 0/0/1 (1 of 19 prompts rated) |
| Distress overrides | 8 flags: 2 baseline, 6 momentary; 0 decisions logged as suppressed |
| Distress signals | Check-in anxiety at the scale ceiling 6, Check-in stress at the scale ceiling 5, AUDIT-C high risk 2, Check-in sadness at the scale ceiling 2, Check-in valence at the scale floor 1 |
| Baseline follow-ups open | 2 |

## By participant

| ID | Enrolled | Phase on Oct 15 | Check-ins | Decisions | Eligible | Sent | Seen | Helpful Y/S/N | Distress (base / mom.) | Follow-up open |
| :--- | :---: | :--- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: |
| RS01 | 09-29 | MRT (day 17) | 79/102 (77%) | 87 | 8 | 7 | 0 | 0/0/0 | 1 / 0 | yes |
| RS02 | 10-05 | MRT (day 11) | 44/66 (67%) | 51 | 10 | 6 | 0 | 0/0/0 | 0 / 0 | no |
| RS03 | 09-29 | MRT (day 17) | 76/102 (75%) | 81 | 8 | 3 | 1 | 0/0/1 | 1 / 0 | yes |
| RS04 | 09-29 | MRT (day 17) | 27/102 (26%) | 32 | 7 | 3 | 0 | 0/0/0 | 0 / 6 | no |
| RS05 | 10-05 | MRT (day 11) | 0/66 (0%) | 0 | 0 | 0 | 0 | 0/0/0 | 0 / 0 | no |

## Definitions

- **Check-ins:** completed scheduled slots out of those delivered (six 2-hour slots, 9:00–21:00 ET).
- **Eligible** decision points are what the reports call *available*: a randomization draw was taken (MSSD above the participant's threshold, no cooldown, daily cap, run-in or distress block). In the 7-day run-in nothing is randomized; a decision that clears the MSSD gate there is logged as suppressed.
- **Seen** is the earlier of a device receipt or a helpfulness rating (Dr. Chang, 2026-10-08). Prompts are silent pushes with no true "open" event, and no device receipt has arrived for any prompt, which points at the receipt pipeline rather than the participants. Notification taps are not counted: none has ever been linked to a prompt.
- **Helpfulness** is the "Was this message helpful right now?" rating after a sent prompt.
- **Distress:** a baseline follow-up stays open until staff record the contact; momentary flags pause prompts for 24 h and never need follow-up. Baseline alcohol and gambling flags do not pause prompts. A paused decision is logged as suppressed only if it would otherwise have been randomized, so a flag can pause prompts without any suppressed row.

## Needs attention

- **RS04** check-in completion is 27/102 (26%); 6 momentary distress flags.
- **RS05** has completed no check-ins since enrolling 10-05 and has no push token, so no reminder or prompt can reach them.
    - They have their Garmin set up, as seen from their Labfront 10-11 export data. 
- Baseline follow-up still open for RS01, RS03 (contact not yet documented).
- No device receipt for any of the 19 sent prompts.
- Wearable data ingestion to database is not populated. 
