---
title: "Paper B: REACT Protocol and Feasibility: Analysis Plan"
author: "Tien (Tyler) Le"
date: "October 29, 2026 (revised from October 12, 2026)"
---

**October 29 revision.** The eating primary outcome is now `B4_emotion_influence` (momentary emotional influence on eating, Likert 1–7), replacing `B4_urge`. The three primary outcomes are the ones registered at ClinicalTrials.gov (NCT07782398; `analytics/analysis-resources/clinicaltrials_outcomes_gov.md`), and `B4_loss_of_control` is the registered eating secondary. `B4_urge` is not registered and is now exploratory. This matches protocol §15.0 ("emotional or uncontrolled eating"), so it needs no protocol amendment. How participants who did not eat are coded is OPEN (§2.2).

**October 12 revision note.** That revision made six changes to the September 30 draft:

1. Table 1 now matches the outcome window as implemented.
2. The primary outcomes are one confirmatory item per construct, with backend item IDs (Table 2).
3. WCLS is stated as the primary causal analysis, with GEE as a comparison only.
4. Suppressed decision points are defined as unavailable.
5. Table 4 now lists only PHQ-9, SCOFF and the Hunger Vital Sign as suspending randomization. The safety table is Table 4; Table 3 is the power table.
6. Sensitivity analysis S2(b) is removed.

Four discrepancies are now decided in favor of the deployed build:

- the outcome window is +60 to about +90 minutes;
- the outcome check-in serves the four domain item sets;
- availability is taken as 0.2;
- DERS-16 stays a Tier 1 moderator.

Each is marked DECIDED below, with the protocol amendment it implies.

# 1. Primary Proximal Effect Estimand

The IRB protocol defines the primary estimand as follows (§15.0, Primary analysis): "The primary estimand is the causal excursion effect: the average difference in the proximal outcome in the window following a decision point at which a prompt was delivered versus not delivered, averaged over available decision points."

Formally, let $t$ index decision points for participant $i$ during the micro-randomization period (study weeks two through five; §9.3). Let $I_{it} \in \{0,1\}$ indicate that the decision point is available, and $A_{it} \in \{0,1\}$ denote randomized assignment to prompt delivery. Let $Y_{i,t+1}$ be the proximal outcome measured in the time-locked outcome window (§2), and $H_{it}$ the participant's history up to the decision point. The causal excursion effect, marginal over history, is

$$\beta_0 = E\left[\, Y_{i,t+1}(\bar A_{i,t-1}, 1) - Y_{i,t+1}(\bar A_{i,t-1}, 0) \;\middle|\; I_{it} = 1 \right] \qquad (1)$$

where $\bar A_{i,t-1}$ is the participant's prior treatment history, so the expectation averages over the treatment histories the trial itself generates [1]. It is an excursion from the protocol at a single decision point, not the cumulative effect of sustained prompting. With a moderator vector $S_{it} \subseteq H_{it}$, the moderated effect $\beta(S_{it})$ conditions on $S_{it}$ (§5).

Treatment is the randomized assignment. In the analysis pipeline,

$$A_{it} = \mathbf{1}\{\texttt{randomization\_draw} < \texttt{randomization\_probability}\} \qquad (2)$$

computed from the values logged at every decision point (§9.3: "Every decision point, whether or not a prompt is sent, is logged with its randomization probability, the draw outcome, the eligible message pool, the selected message, and delivery timestamps").

> **DISCREPANCY: Assignment vs. delivery.** The protocol's estimand contrasts decision points "at which a prompt was delivered versus not delivered." The software separates these states:
>
> 1. `JITAILog.send_prompt` is reset to False after a winning draw when no message can be selected (`backend/app/tasks.py::_evaluate_user`, empty-pool branch).
> 2. A failed push keeps `send_prompt = True` with `status = 'failed'` (`notification_service.mark_delivery_failed`).
>
> Contrasting delivered prompts conditions on events after randomization, which breaks exchangeability. The estimand is therefore defined on assignment.

# 2. Proximal Outcome Window

## 2.1 Time-Locked Outcome Assessment

Protocol §9.2: "During the micro-randomization period, the first check-in within two hours after any decision point presents the three behavior domains together for a time-locked outcome window; if no scheduled check-in falls in that window the app inserts one brief extra check-in, capped at four per day."

Protocol §10.0 (Schedule of Measures): "During the micro-randomization period, the first check-in within two hours after any decision point presents all four domain item sets together for a time-locked outcome window."

**As built.** Every available decision point opens a time-locked outcome window at `decision_made_at`, whatever the randomized assignment (`_latest_outcome_window`, `backend/app/views.py`). The randomized-out arm receives no notification at the decision. The reminder at +60 minutes announces its outcome check-in, exactly as it does in the sent arm. An earlier build sent the randomized-out arm a check-in notification at the decision; that was removed on October 5, 2026, because the 60-minute lock leaves nothing to open at that time.

| Time after the decision point | What `/ema/next/` serves | Notification |
|---|---|---|
| 0 to 60 min | Only the C0 post-prompt rating, after a delivered prompt that has not been rated (§10.0). Scheduled check-ins are held back in both arms (`reason: outcome_window_pending`). | None in either arm. Scheduled check-in reminders are held back in both arms. |
| At +60 min | — | If the outcome check-in is unanswered and the participant is under the daily cap of four outcome check-ins: one visible reminder, identical in both arms (`_maybe_send_outcome_reminder`). |
| +60 min, for 30 min after the reminder | The outcome check-in: current emotions and situation with the four domain item sets (`POST_PROMPT_ITEM_IDS` = B1, B2, B4, B5, B6, B7), served as `extra_check_in` and linked to the decision point (`source_jitai_log`). It is served only while the reminder is open, for the 30-minute response window (`EMA_RESPONSE_WINDOW_MINUTES`). | None further. |
| Once answered, or once the window closes (about +90 min) | Ordinary scheduled check-ins resume. | Scheduled check-in reminders resume. |

Table 1: Outcome window lifecycle and notification dispatch rules, as implemented.

Outcome check-ins share the protocol's cap of four per day. The 60-minute lock (`OUTCOME_CHECK_IN_DELAY_MINUTES`) keeps the timing of the measurement independent of the assignment arm. Without it, a delivered prompt brings the participant into the app, so the treated arm would answer within minutes while the control arm waited for the next scheduled check-in.

**Analysis definition.** For each available decision point, the proximal outcome is taken from the first completed check-in linked to it (`source_jitai_log_id`, type `post_prompt` or `extra_check_in`) that satisfies the following, where `expires_at` is the check-in's own deadline, copied from its reminder (30 minutes after the reminder is sent at +60 minutes):

$$\texttt{decision\_made\_at} + 60\ \text{min} \;\le\; \texttt{sent\_at} \;\le\; \texttt{expires\_at} \;\approx\; \texttt{decision\_made\_at} + 90\ \text{min}. \qquad (3)$$

Values are read from `EMAItemResponse.value_numeric` and `value_choice` by `sub_item_id`. The EMA-level mood, stress and energy fields are not used, because the submission handler does not populate them. A decision point with no completed check-in in this interval has a missing outcome (§6).

> **DECIDED: Outcome window.** The analysis uses the window as deployed: +60 minutes to the outcome check-in's deadline, about +90 minutes. The check-in is answerable only while its reminder is open (30 minutes after it is sent at +60 minutes). A participant with no push token, or one who has reached the daily cap, receives no reminder and so no outcome check-in; that decision point has a missing outcome (§6). *Protocol amendment:* §9.2, §10.0 and §15.0 change from "within two hours after" the decision point to "between 60 and about 90 minutes after" it.

> **DECIDED: Domain count.** The outcome check-in serves the deployed set, `POST_PROMPT_ITEM_IDS` = B1, B2, B4, B5, B6, B7: current emotions and situation plus the four domain item sets (B4 eating, B5 emotion regulation, B6 alcohol, B7 online activity). The outcomes in §2.2 are drawn from these items, as in the outcome summary. *Protocol amendment:* §9.2's "the three behavior domains" changes to "the four domain item sets", matching §10.0.

## 2.2 Primary Behavioral Outcomes

Protocol §15.0: "Proximal outcomes are drawn from the time-locked check-in within two hours after the decision point: self-reported urge to post reactively, self-reported reactive online behavior, self-reported drinking and drinking urge, and self-reported emotional or uncontrolled eating, each analyzed separately."

Each construct has one confirmatory item. Each is fitted in its own WCLS model. Backend IDs are the values stored in `EMAItemResponse.item_id` and `EMAItemResponse.sub_item_id`.

| Construct | Backend ID (item / sub-item) | Item text | Scale | Recall | Model |
|---|---|---|---|---|---|
| Urge to post reactively | `B7` / `B7_urge` | "Right now, how strong is your urge to post or reply about something that upset you?" | Likert 1–7 | Now | Linear WCLS, all participants |
| Drinking urge | `B6` / `B6_urge` | "Right now, how strong is your urge to drink alcohol?" | Likert 1–7 | Now | Linear WCLS, all participants |
| Emotional influence on eating | `B4` / `B4_emotion_influence` | "If yes: how much did emotions influence your eating?" | Likert 1–7 (1 = Not at all; 7 = A great deal) | Since the previous check-in | Linear WCLS; coding for participants who did not eat is OPEN (below) |

Table 2: Primary confirmatory outcomes, as registered at ClinicalTrials.gov (NCT07782398).

`B7_urge` and `B6_urge` are asked of every participant at every outcome check-in. `B4_emotion_influence` is asked only if `B4_ate` = Yes (`backend/app/ema_catalog.py`), and eating can itself be affected by the prompt, so a model fitted only to participants who ate would condition on an event after the decision point.

> **OPEN: Participants who did not eat (needs PI sign-off).** The registration defines the measure as the 1–7 rating and gives no value for a check-in at which nothing was eaten. The default is to code `B4_emotion_influence` at the scale floor (1, "Not at all") when `B4_ate` = No and to fit linear WCLS on every answered outcome check-in, which keeps the estimand a causal excursion effect. Two sensitivity analyses are prespecified: the literal reading, fitted only where `B4_ate` = Yes, and the binary emotional-eating composite below. The effect of the prompt on `B4_ate` itself is reported as a diagnostic.

**Secondary outcomes.**

- **Online behavior:** `B7_posted` (yes/no), `B7_charged` (Likert 1–7) and `B7_self_stopped` (3-level choice), all recalled over "the past few hours", which can include time before the decision point.
- **Alcohol today:** `B6_consumed` (yes/no) and `B6_drink_count` (count, asked if `B6_consumed` = Yes). Their "today" recall includes drinking before the decision point, which the prompt cannot have caused. `B6_drink_count` is analyzed as the within-day change from the decision-point check-in to the outcome check-in.
- **Eating:** `B4_loss_of_control` (Likert 1–7, "since the previous check-in") is the registered eating secondary. Like `B4_emotion_influence` it is asked only if `B4_ate` = Yes, so it is handled as the primary is under the OPEN note above. Two binary composites, defined for everyone, support the rating analyses and are not registered outcomes:
  - emotional eating = 1 if `B4_ate` = Yes and `B4_emotion_influence` is 5 or more, otherwise 0;
  - uncontrolled eating is defined the same way from `B4_loss_of_control`.

  `B4_ate` (yes/no) is analyzed as a diagnostic of whether the prompt changes eating. `B4_urge` ("Right now, how strong is your urge to eat?", Likert 1–7) is exploratory and not registered; it stays in the item bank because it feeds message routing.
- **Affect:** `B1_valence` and `B2_stress` (Likert 1–7).

Of the outcomes above, the registered secondaries are `B7_posted`, `B6_drink_count` and `B4_loss_of_control` (plus the feasibility measures). The registration describes `B6_drink_count` as drinks "since the previous check-in", whereas the item asks about today, hence the within-day-change handling above. `B7_charged`, `B7_self_stopped`, `B6_consumed`, `B1_valence`, `B2_stress`, `B4_ate`, the eating composites and `B4_urge` are additional analyses and are not registered.

Binary secondary outcomes are estimated on the risk-difference scale, with log relative-risk models [5] as a further specification.

# 3. Weighted-and-Centered Least Squares Analysis

Protocol §15.0: "This is estimated by weighted and centered least squares (Boruvka et al., 2018), with weights derived from the known randomization probability of 0.5 and centering on the randomization probability, which yields a consistent estimate of the marginal excursion effect without requiring a model for the outcome under no treatment. Standard errors use a sandwich estimator with small-sample correction, clustering at the participant level."

**WCLS is the primary causal analysis.** A generalized estimating equation (GEE) fit of the same outcomes is reported as a comparison only. It is not an estimate of the causal excursion effect, because it neither weights by nor centers on the randomization probabilities.

## 3.1 Treatment Assignment and Weighting

Randomization is a two-stage sequential draw (`backend/app/tasks.py::_evaluate_user`). Each stage is analyzed with its own logged probability, never an assumed value.

1. **Prompt assignment:** draw $U_{it} \sim U(0,1)$ and assign $A_{it} = \mathbf{1}\{U_{it} < p_{it}\}$. Here $p_{it}$ is the logged `randomization_probability` for that row (currently `JITAI_RANDOMIZATION_PROBABILITY` = 0.5).
2. **Message arm:** if $A_{it} = 1$, a second draw allocates the coping intervention or the active control. Its logged probability is `arm_randomization_probability` (currently 0.5).

Let $\tilde p$ denote the mean of the logged probabilities $p_{it}$. Each decision point is weighted by

$$W_{it} = \left(\frac{\tilde p}{p_{it}}\right)^{A_{it}} \left(\frac{1 - \tilde p}{1 - p_{it}}\right)^{1 - A_{it}}. \qquad (4)$$

When every $p_{it}$ equals 0.5, every weight equals 1. Evaluating the weight row by row keeps the analysis valid if the probability changes during deployment. Positivity ($0 < p_{it} < 1$) is checked before model fitting.

## 3.2 Centered Treatment Indicator

Treatment enters the model centered as $(A_{it} - \tilde p)$. For any history $H_{it}$ with $I_{it} = 1$,

$$E\left[W_{it}(A_{it} - \tilde p) \mid H_{it}, I_{it} = 1\right] = p_{it}\frac{\tilde p}{p_{it}}(1 - \tilde p) + (1 - p_{it})\frac{1 - \tilde p}{1 - p_{it}}(0 - \tilde p) = 0. \qquad (5)$$

The weighted, centered indicator is therefore orthogonal to any function of history. Errors in the control terms $g(H_{it})$ affect precision but not consistency, provided outcome observation does not depend on assignment.

## 3.3 Estimation of the Causal Excursion Effect

The parameter vector $\hat\theta = (\hat\alpha^\top, \hat\beta^\top)^\top$ solves the weighted estimating equations over available decision points with observed outcomes:

$$\sum_{i=1}^{n} \sum_t I_{it} W_{it} \left( Y_{i,t+1} - g(H_{it})^\top \alpha - (A_{it} - \tilde p) f(S_{it})^\top \beta \right) \begin{pmatrix} g(H_{it}) \\ (A_{it} - \tilde p) f(S_{it}) \end{pmatrix} = 0. \qquad (6)$$

- **Primary marginal model:** $f(S_{it}) = 1$, so that $\beta = \beta_0$. All three primary outcomes are Likert 1–7, so the primary model is linear WCLS; ordinal models are sensitivity checks.
- **Control vector $g(H_{it})$:** intercept; valence (`B1_valence`) and stress (`B2_stress`) at the decision check-in; hour of day (Eastern, centered at 15:00); study day (centered at mid-study).
- **Working independence:** observations within a participant are treated as independent in the estimating equations, which keeps the point estimate consistent without a correct time-series covariance model. Repeated measures are handled in the variance estimator.

## 3.4 Statistical Inference and Power

**Covariance estimation.** Inference uses the robust sandwich estimator $\widehat{\mathrm{Var}}(\hat\theta) = B^{-1} M B^{-1}$ with the Mancl–DeRouen small-sample correction [3]:

$$B = \sum_{i=1}^{n} X_i^\top W_i X_i, \qquad M = \sum_{i=1}^{n} X_i^\top W_i (I - H_{ii})^{-1} r_i r_i^\top (I - H_{ii})^{-\top} W_i X_i, \qquad (7)$$

where $H_{ii} = X_i B^{-1} X_i^\top W_i$. Test statistics are referred to Student's t distribution with $n - \dim(\alpha) - \dim(\beta)$ degrees of freedom.

**Sample size and availability.** The protocol assumed an availability of 0.6 (§7.0). In the deployed system a decision point is available only when MSSD exceeds the participant's expanding 80th percentile, so availability is about 0.2. Following [2], the noncentrality parameter for the primary test is

$$\lambda = N d^{2} p(1 - p) \sum_t E[I_t], \qquad \text{Power} = \Pr\left(F_{1, N-q-1}(\lambda) > F^{\text{crit}}_{1, N-q-1}\right). \qquad (8)$$

Protocol §7.0 (Sample Size): "Sample size follows the approach for micro-randomized trials in Liao et al. (2016). With about 80 participants, micro-randomization active for roughly four weeks, up to six decision points per day, an assumed availability near 0.6, and a send probability of 0.5, each participant contributes on the order of a hundred available randomized decision points, giving several thousand across the sample and about half that with a prompt delivered."

The protocol's power claim, detection of "a standardized proximal main effect in the range of 0.10 to 0.15 at about 80 percent power," still holds at an availability of 0.2. With N = 80, 28 days of micro-randomization at six decision points per day, and p = 0.5, the primary test has 80% power (two-sided alpha 0.05) to detect:

| Scenario (N = 80) | Available DP per person | Total DP | MDE (80% power) | Power at d = 0.10 / 0.15 |
|---|---|---|---|---|
| Protocol target (availability 0.6) | 100.8 | 8,064 | 0.063 | 0.99 / 1.00 |
| Deployed system (availability 0.2) | 33.6 | 2,688 | 0.109 | 0.73 / 0.97 |
| + 75% completion benchmark | 25.2 | 2,016 | 0.126 | 0.60 / 0.91 |
| + 75% outcome response rate | 18.9 | 1,512 | 0.146 | 0.48 / 0.82 |
| Same, with N = 70 retained | 18.9 | 1,323 | 0.156 | 0.43 / 0.77 |

Table 3: Statistical power across study engagement scenarios.

The minimum detectable effect is 0.109 under full engagement, 0.126 at the 75% check-in completion benchmark, 0.146 when 75% of outcome check-ins are answered, and 0.156 if retention falls to N = 70. These lie at the upper end of the protocol's 0.10 to 0.15 range. Across 1,000 simulated cohorts, empirical power was 0.784 to 0.798 at the benchmark scenarios, with type I error 0.042 to 0.058.

These minimum detectable effects assume an outcome with similar variance at every available decision point, as for `B7_urge` and `B6_urge`. `B4_emotion_influence` is asked only when `B4_ate` = Yes, so under the default coding most answers sit at the scale floor, and under the literal reading it is missing for non-eaters. Its detectable effect therefore depends on the observed eating rate and rating variance, and is recomputed from Phase 1 data before the second wave.

> **DECIDED: Availability of 0.2.** The analysis plan uses an availability of 0.2, the value from the simulation (0.20 of evaluable decision points in the Paper A decision log) and the power computation above. Each participant then contributes about 19 to 34 available decision points (about 1,500 to 2,700 across the sample) and receives about 0.6 prompts per day (six decision points times 0.2 times 0.5). *Protocol amendment:* §7.0's "on the order of a hundred available randomized decision points" becomes "roughly 20 to 35", and §9.3's "about two to three prompts per day" becomes "about one prompt every one to two days, never more than four in a day."

# 4. Availability and Decision Points

Protocol §9.3: "Availability. A decision point is unavailable, and no prompt is delivered, when the participant is asleep according to device data, when the device has not synced recently enough to evaluate the signal, when a prompt has been delivered within the preceding 60 minutes, when the daily cap has been reached, or when a safety override is in effect. Unavailable decision points are recorded and are handled explicitly in the analysis rather than being ignored."

A decision point is created by any completed check-in containing valence, stress and arousal. It is available ($I_{it} = 1$) only when:

1. MSSD exceeds the participant's threshold (above the 80th percentile, with at least 3 earlier values);
2. no prompt has been delivered in the preceding 60 minutes;
3. fewer than four prompts have been delivered that day;
4. the study day is 7 or later (the run-in is complete);
5. no distress flag that suspends randomization is active (Table 4).

**Suppressed decision points are unavailable, not "no send."** A decision point stopped by the run-in or by a distress flag gets $I_{it} = 0$: no draw is taken, no probability is recorded, its status is `suppressed` with a `suppression_reason`, and it opens no outcome window. It never enters the WCLS as $A_{it} = 0$. The control arm is made up only of available decision points whose draw assigned no prompt.

> **DISCREPANCY: System availability implementations.**
>
> - **Sleep and sync status:** wearable data are not yet used in triggering; a completed check-in is taken as evidence that the participant is awake.
> - **Decision point frequency:** the protocol cites "up to six decision points per day." In production, post-prompt and extra check-ins can themselves create decision points, giving up to ten per day.

The cooldown and the daily cap count delivered prompts only (`_cooldown_cap_reason`, `backend/app/tasks.py`), on Eastern calendar days. This matches §9.3.

## 4.1 Safety Override and Distress Flags

Protocol §11.0: "During the intensive period, any distress signal suspends prompt randomization for that participant and the app shows a resource card instead of a coping message."

| Flag level | Trigger condition | Duration | System response |
|---|---|---|---|
| Momentary | A check-in at a scale boundary: `B1_valence` = 1, `B2_stress` = 7, `B1_affect_sad` = 5 or `B1_affect_anxious` = 5 | 24 hours | Randomization suspended; resource card shown in the app. |
| Baseline, suspending | Scored Qualtrics screen: PHQ-9 self-harm item positive or PHQ-9 total moderately severe/severe; SCOFF positive; Hunger Vital Sign (food insecurity) positive | Until staff document contact | Randomization suspended; study team alerted by Qualtrics. |
| Baseline, alert only | Scored Qualtrics screen: AUDIT-C high risk; PGSI problem gambling | — | **Randomization not suspended.** Study team alerted by Qualtrics; follow-up at the next visit. |
| Manual | Disclosure of risk to self or others, entered by staff (never by the import) | Until staff document contact | Randomization suspended. |

Table 4: Safety override classifications and intervention routing.

This is Table 4. The backend enforces the same split: AUDIT-C and PGSI are the alert-only signals (`BASELINE_ALERT_ONLY_SIGNALS`, `backend/dashboard/data/config.py`), and a baseline flag suspends randomization only if it carries a signal outside that set (`DistressFlag.is_active`). Decision points suppressed by a flag are unavailable, as defined in §4.

# 5. Moderation Analyses

## 5.1 Model Specification

Moderated causal excursion effects are estimated by setting $f(S_{it}) = (1, S_{it})^\top$. The control set $g(H_{it})$ must include the main effect of every $S_{it}$. Leaving $S_{it}$ out of $g(H_{it})$ lets confounding leak into $\hat\beta$ when missingness depends on assignment. Continuous moderators are centered.

## 5.2 Confirmatory Tier 1 Moderators

> **DECIDED: DERS-16.** DERS-16 stays a Tier 1 confirmatory moderator, as protocol §1.0 specifies, tested against all three primary outcomes (Table 5). *Protocol amendment:* add DERS-16 to the Tier 1 list in §15.0, where it is currently missing.

| Tier 1 moderator | Scale | Paired proximal behavioral outcome |
|---|---|---|
| SUPPS-P | Negative / Positive Urgency | Urge to post reactively (`B7_urge`) |
| DMQ-R | Coping Drinking Motives | Drinking urge (`B6_urge`) |
| TFEQ-R18 | Emotional / Uncontrolled Eating | Emotional influence on eating (`B4_emotion_influence`) |
| DERS-16 | Total score | All three primary outcomes |
| MAIA-2 | Noticing, Body Listening | All three primary outcomes |

Table 5: Pre-specified Tier 1 moderation pairings.

## 5.3 Message-Type Sub-Studies

Message effectiveness is compared in two tiers:

1. **Coping vs. active control (primary):** WCLS restricted to $A_{it} = 1$, with the message arm as treatment, weighted and centered on its logged `arm_randomization_probability`.
2. **Technique families (CBT vs. ACT):** compared within category pools, conditioning on the empirical assignment probability P(CBT | pool) = number of CBT messages / total messages in the pool.

# 6. Missing Data and Sensitivity Analyses

Missingness operates at two levels:

- **Unavailable decision points** are handled by definition: the estimand conditions on $I_{it} = 1$.
- **Missing outcome responses:** available decision points without a completed outcome check-in in the window are excluded in complete-case estimation.

| Label | Sensitivity dimension | Analysis | Design boundary |
|---|---|---|---|
| S1 | Outcome window | Retired. The primary window already ends at about +90 min (§2.1), so closing it at +90 min no longer differs from the primary analysis. | The label is kept so that S2 to S6 keep their numbers. |
| S2 | Availability definition | Exclude decision points created by extra check-ins, keeping only scheduled check-ins (matching "up to six decision points per day"). | Cannot add decision points that were never randomized. |
| S3 | MSSD threshold | Re-evaluate the threshold at the 85th and 90th percentiles. | Cannot evaluate below the 80th percentile. |
| S4 | Compliance | Exclude participants with less than 75% check-in completion. | Reported as a sub-cohort model alongside the full sample. |
| S5 | Outcome missingness | Inverse-probability weighting conditional on $A_{it}$, time and affect at the decision check-in. | Run if observation rates differ by arm. |
| S6 | Legacy protocol | Analyze decision points before the fixed-lag cutover with the next scheduled check-in. | Reported separately, never pooled with the main trial. |

Table 6: Pre-specified sensitivity analyses.

S2 previously had a second part, (b), which recounted the cooldown on delivered prompts only. The deployed cooldown now does exactly that (§4), so S2(b) is removed. S3 to S6 keep their labels.

# 7. References

1. A. Boruvka, D. Almirall, K. Witkiewitz, and S. A. Murphy. Assessing time-varying causal effect moderation in mobile health. *Journal of the American Statistical Association*, 113(523):1112–1121, 2018.
2. P. Liao, P. Klasnja, A. Tewari, and S. A. Murphy. Sample size calculations for micro-randomized trials in mHealth. *Statistics in Medicine*, 35(12):1944–1971, 2016.
3. L. A. Mancl and T. A. DeRouen. A covariance estimator for GEE with improved small-sample properties. *Biometrics*, 57(1):126–134, 2001.
4. I. Nahum-Shani, S. N. Smith, B. J. Spring, L. M. Collins, K. Witkiewitz, A. Tewari, and S. A. Murphy. Just-in-time adaptive interventions (JITAIs) in mobile health: Key components and design principles for ongoing health behavior support. *Annals of Behavioral Medicine*, 52(6):446–462, 2018.
5. T. Qian, H. Yoo, P. Klasnja, D. Almirall, and S. A. Murphy. Estimating time-varying causal excursion effects in mobile health with binary outcomes. *Biometrika*, 108(3):507–527, 2021.
6. T. Qian, A. E. Walton, L. M. Collins, P. Klasnja, S. T. Lanza, I. Nahum-Shani, et al. The microrandomized trial for developing digital interventions: Experimental design and data analysis considerations. *Psychological Methods*, 27(5):874–894, 2022.
7. S. Jahng, P. K. Wood, and T. J. Trull. Analysis of affective instability in ecological momentary assessment. *Psychological Methods*, 13(4):354–375, 2008.
