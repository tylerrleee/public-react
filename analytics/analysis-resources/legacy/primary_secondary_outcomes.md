---
title: "REACT Micro-Randomized Trial Analysis Specification and Decision Protocol: IRB-01"
author: "Tien (Tyler) Le"
date: "October 29, 2026 (revised from October 12, 2026)"
---

# 1. Primary and Secondary Outcomes (protocol §15.0)

Every outcome is read from the time-locked outcome check-in, which opens 60 minutes after the decision point and closes at the check-in's deadline, about 90 minutes after it (30 minutes after the +60-minute reminder). Backend IDs are the values stored in `EMAItemResponse.item_id` and `EMAItemResponse.sub_item_id`, as defined in `backend/app/ema_catalog.py`. Which outcomes are primary and secondary follows the registration at ClinicalTrials.gov (NCT07782398; `analytics/analysis-resources/clinicaltrials_outcomes_gov.md`).

## 1.1 Primary outcomes: one confirmatory item per construct

| Construct | Backend ID (item / sub-item) | Item text | Scale | Recall | Analysis |
|---|---|---|---|---|---|
| Urge to post reactively | `B7` / `B7_urge` | "Right now, how strong is your urge to post or reply about something that upset you?" | Likert 1–7 (1 = No urge at all; 7 = Extremely strong urge) | Now | Linear WCLS, all participants [1] |
| Drinking urge | `B6` / `B6_urge` | "Right now, how strong is your urge to drink alcohol?" | Likert 1–7 (same anchors) | Now | Linear WCLS, all participants [1] |
| Emotional influence on eating | `B4` / `B4_emotion_influence` | "If yes: how much did emotions influence your eating?" | Likert 1–7 (1 = Not at all; 7 = A great deal) | Since last check-in | Linear WCLS [1]; coding for participants who did not eat is OPEN (below) |

Each construct has a single confirmatory item, and each is analyzed in its own model. `B7_urge` and `B6_urge` are asked of every participant at every outcome check-in, whatever they answered to other items. `B4_emotion_influence` is asked only if `B4_ate` = Yes, and eating can itself be affected by the prompt, so a model fitted only to participants who ate would condition on an event after the decision point.

**OPEN: participants who did not eat (needs PI sign-off).** The registration defines the measure as the 1–7 rating and gives no value for a check-in at which nothing was eaten. The default codes `B4_emotion_influence` at the scale floor (1, "Not at all") when `B4_ate` = No and fits linear WCLS on every answered outcome check-in, which keeps the estimand a causal excursion effect. Prespecified sensitivity analyses are the literal reading (fitted only where `B4_ate` = Yes) and the emotional-eating composite in §1.2. The effect of the prompt on `B4_ate` is reported as a diagnostic.

## 1.2 Secondary outcomes

| Domain | Backend ID (item / sub-item) | Scale | Recall | Analysis and reason it is secondary | Registry (NCT07782398) |
|---|---|---|---|---|---|
| Online behavior | `B7` / `B7_posted` | Yes/No (1 = Yes; 0 = No) | Past few hours | Weighted and centered risk difference; log-RR as a further specification [2]. The recall window can include time before the decision point. | Registered |
| Online behavior | `B7` / `B7_charged` | Likert 1–7 | Past few hours | Linear WCLS. Same recall caveat. | Not registered |
| Online behavior | `B7` / `B7_self_stopped` | 3-level choice (Yes; No; Did not feel the urge) | Past few hours | Categorical excursion model. Same recall caveat. | Not registered |
| Alcohol, today | `B6` / `B6_consumed` | Yes/No (1 = Yes; 0 = No) | Today | Risk difference [2]. Not primary: "today" includes drinking before the decision point, which the prompt cannot have caused. | Not registered |
| Alcohol, today | `B6` / `B6_drink_count` | Count, 0 or more; asked only if `B6_consumed` = Yes | Today | Count model, analyzed as the within-day change from the decision-point check-in to the outcome check-in. Same reason as above. | Registered; the registration says "since the previous check-in", the item asks about today |
| Eating, registered | `B4` / `B4_loss_of_control` | Likert 1–7 (1 = Not at all; 7 = Completely lost control); asked only if `B4_ate` = Yes | Since last check-in | Linear WCLS, with participants who did not eat handled as for the primary (§1.1). | Registered |
| Eating, supporting | `B4` / `B4_emotion_influence` and `B4_loss_of_control` (composites) | Binary, defined for everyone | Since last check-in | Emotional eating = 1 if `B4_ate` = Yes and `B4_emotion_influence` is 5 or more, else 0; uncontrolled eating = 1 if `B4_ate` = Yes and `B4_loss_of_control` is 5 or more, else 0. Risk difference [2]. Sensitivity analysis for the primary and support for the secondary; never a model fitted only to participants who ate. | Not registered |
| Eating, diagnostic | `B4` / `B4_ate` | Yes/No (1 = Yes; 0 = No) | Since last check-in | Risk difference [2]. Shows whether the prompt changes eating at all, which indicates how much the coding for non-eaters matters. | Not registered |
| Eating, exploratory | `B4` / `B4_urge` | Likert 1–7 (1 = No urge at all; 7 = Extremely strong urge) | Now | Linear WCLS, all participants. It was the eating primary until October 29; the registration does not list it. It stays in the item bank because it feeds message routing. | Not registered |
| Affective valence | `B1` / `B1_valence` | Likert 1–7 (1 = Very negative; 7 = Very positive) | Now | Linear WCLS. | Not registered |
| Perceived stress | `B2` / `B2_stress` | Likert 1–7 (1 = Not at all; 7 = Extremely) | Now | Linear WCLS. | Not registered |

The registration also lists feasibility secondaries (check-in completion, prompt response, valid wearable data, retention, hair-sample yield, prompt helpfulness, System Usability Scale), which are reported in the feasibility analysis rather than here.

The cutoff of 5 or more on a 7-point item follows the `>= 5` convention in `ROUTING_TRIGGER_RULES` (`backend/app/ema_catalog.py`), which applies it to `B4_urge`, not to the two items above.

# 2. Confirmatory Tier-1 Moderators and Time

- **Baseline trait inventories:**
  - SUPPS-P: Negative and Positive Urgency subscales.
  - DMQ-R: Coping Drinking Motives subscale.
  - TFEQ-R18: Emotional and Uncontrolled Eating, paired with `B4_emotion_influence`.
  - DERS-16: Difficulties in Emotion Regulation total.
  - MAIA-2: Noticing and Body Listening subscales.
- **Temporal moderators (within person):**
  - Hour of day: decision time in Eastern time, centered at 15:00.
  - Study day: day in study, centered at mid-study; evaluates attenuation or habituation across weeks 2 to 5.
- **Moderator adjustment:** the main effect of each moderator is included in the control terms, so the treatment contrast stays orthogonal to it.

# 3. Estimator Selection

- **Primary outcomes** (`B7_urge`, `B6_urge`, `B4_emotion_influence`, all Likert 1–7): linear WCLS as the primary model [1]. Ordinal models are sensitivity checks only.
- **Secondary binary outcomes** (`B7_posted`, `B6_consumed`, `B4_ate`, and the two eating composites as supporting analyses): weighted and centered risk difference, with log relative risk as a further specification [2].
- **Secondary Likert outcomes** (`B4_loss_of_control`, `B7_charged`, `B1_valence`, `B2_stress`): linear WCLS, as for the primary outcomes. The exploratory `B4_urge` is analyzed the same way.

# 4. Coping vs. Active Control Sub-Study

- **Two-stage randomization:** at each available decision point, prompt delivery is randomized with probability 0.5. If a prompt is sent, its message arm is randomized again with probability 0.5: coping JITAI or active control.
- **Causal estimand:** the difference in mean outcome between message arms among decision points where a prompt was sent. This separates the content of the coping skill from the effect of receiving an alert.
- **Estimation:** WCLS on the sent decision points, with the arm indicator centered on the arm randomization probability.

# 5. Detectable Effect Sizes

- **Parameters:** N = 80; 28 days of micro-randomization; 6 decision points per day; availability 0.2 (simulation and power computation); two-sided alpha 0.05; 80% power.
- **Sub-study scaling:** restricting to sent decision points halves the effective sample, so the detectable effect for the arm comparison is larger than for the main excursion effect by a factor of the square root of 2, about 1.414.
- **Eating primary:** these figures assume an outcome with similar variance at every available decision point. `B4_emotion_influence` is asked only when `B4_ate` = Yes, so its detectable effect depends on the observed eating rate and rating variance. Recompute from Phase 1 data before the second wave.

# References

1. A. Boruvka, D. Almirall, K. Witkiewitz, S. A. Murphy. *Journal of the American Statistical Association*, 113(523):1112–1121, 2018.
2. T. Qian, H. Yoo, P. Klasnja, D. Almirall, S. A. Murphy. *Biometrika*, 108(3):507–527, 2021.
