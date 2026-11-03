"""
Does the single-item calibration carry over to the production composite?

Paper A's simulations feed the decision engine one 1-7 item. Production
(backend/app/tasks.py::build_decision_frame) feeds it the raw mean of
B1_valence, B2_stress and B1_arousal per completed check-in, and
calculate_mssd differences consecutive completed check-ins, so the differences
bridge missed prompts and cross the overnight gap.

Every input model here is run through the unmodified engine
(decision_engine.calculate_mssd / apply_decision_rules). They differ only in
what is fed to it:

    signal     "single" = B1_valence alone (integer grid), "composite" = the
               three-item mean (1/3 grid)
    bridge     False keeps missed prompts as NaN rows, so a difference touching
               a miss is dropped (the published simulation); True drops the
               rows, so differences span the gap (production)
    night      latent steps across the night: 1 = the published AR(1), 4 =
               12 h at the 3 h prompt spacing, 31 = effectively a reset
    night_break  True stops differences crossing the night (a counterfactual,
               not what the engine does), to isolate their effect

Used by sensitivity_analysis.ipynb (calibration) and
robustness_misspecification.ipynb (volatility shifts).
"""

import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for _p in (os.path.join(REPO, "backend"), os.path.join(REPO, "backend", "syntheticData")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from decision_engine.decision_engine import apply_decision_rules, calculate_mssd
from synthetic_generator import (FIELD_ITEM_CORRELATIONS, composite_expected_mssd,
                                 generate_cohort_composite)

THRESHOLD_QUANTILE = 0.80
COOLDOWN_MINUTES = 60
MAX_PROMPTS_PER_DAY = 4
MSSD_WINDOW = 3
RUN_IN_DAYS = 7
EMA_PER_DAY = 5
SINGLE_ITEM = "B1_valence"
STUDY_START = pd.Timestamp("2026-08-25")

MODELS = {
    "A single item (published)": dict(signal="single", bridge=False, night=1),
    "B composite": dict(signal="composite", bridge=False, night=1),
    "C composite, production": dict(signal="composite", bridge=True, night=4),
}
VALENCE_STRESS_SWEEP = (-0.6, 0.0, 0.6)
ABLATIONS = {
    "C, misses dropped": dict(signal="composite", bridge=False, night=4),
    "C, night = 1 step": dict(signal="composite", bridge=True, night=1),
    "C, night = reset": dict(signal="composite", bridge=True, night=31),
    "C, no overnight differences": dict(signal="composite", bridge=True, night=4,
                                        night_break=True),
}


def spread_timestamps(frame, ema_per_day=EMA_PER_DAY, start=STUDY_START):
    """Prompt k of day d at 09:00 + 3h*k, as in robustness_misspecification.ipynb."""
    frame = frame.copy()
    step = 12.0 / (ema_per_day - 1)
    k = frame["prompt_idx"].to_numpy() % ema_per_day
    hours = frame["day"].to_numpy() * 24.0 + 9.0 + k * step
    frame["timestamp"] = start + pd.to_timedelta(hours, unit="h")
    return frame


def make_cohort(users, days, seed, resp_rate=0.80, corr=FIELD_ITEM_CORRELATIONS,
                night=1, scale_paths=None, mu=None, sigma=None, rho=None, prefix="u"):
    """generate_cohort_composite with readable user ids and real prompt times."""
    cohort = generate_cohort_composite(
        users=users, days=days, ema_per_day=EMA_PER_DAY, seed=seed,
        resp_rate=resp_rate, corr=corr, overnight_steps=night - 1,
        user_ids=[f"{prefix}{i:03d}" for i in range(users)], scale_paths=scale_paths,
        mu=mu, sigma=sigma, rho=rho)
    return spread_timestamps(cohort)


def engine_input(cohort, signal, bridge):
    """The frame the engine sees, plus each row's ground truth for its own signal."""
    frame = cohort.copy()
    if signal == "single":
        frame["ema"] = frame[SINGLE_ITEM]
        frame["latent_signal"] = frame[f"latent_{SINGLE_ITEM}"]
        sigma = frame[f"true_sigma_{SINGLE_ITEM}"]
        frame["true_mssd"] = 2.0 * sigma ** 2 * (1.0 - frame[f"true_rho_{SINGLE_ITEM}"])
    elif signal == "composite":
        frame["latent_signal"] = frame["latent"]
        frame["true_mssd"] = frame["true_expected_mssd"]
    else:
        raise ValueError(signal)
    frame = add_latent_truth(frame)
    if bridge:
        frame = frame[frame["ema"].notna()]
    return frame.reset_index(drop=True)


def add_latent_truth(frame, target=1.0 - THRESHOLD_QUANTILE):
    """Ground truth on the gap-free latent signal, as in the robustness notebook.

    Rolling-3 MSSD of the noise-free latent over every prompt, standardised by
    the current volatility multiplier, so the per-participant top 20% marks real
    high-instability moments for whatever regime the participant is in.
    """
    frame = frame.sort_values(["user_id", "prompt_idx"]).copy()
    d2 = frame.groupby("user_id")["latent_signal"].diff() ** 2
    lat = (d2.groupby(frame["user_id"]).rolling(MSSD_WINDOW, min_periods=1).mean()
             .reset_index(level=0, drop=True))
    frame["latent_mssd_std"] = lat / frame["scale_t"] ** 2
    cut = frame.groupby("user_id")["latent_mssd_std"].transform(lambda s: s.quantile(1.0 - target))
    frame["truth_high_vol"] = frame["latent_mssd_std"] > cut
    return frame


def _overnight_flags(frame):
    """Mark differences that cross the night, and decisions whose window holds one."""
    prev_day = frame.groupby("user_id")["day"].shift(1)
    crosses = (frame["day"] != prev_day) & frame["ema_diff_squared"].notna()
    frame["overnight_diff"] = crosses
    frame["overnight_window"] = (
        crosses.astype(float).groupby(frame["user_id"])
        .rolling(MSSD_WINDOW, min_periods=1).max()
        .reset_index(level=0, drop=True).astype(bool))
    first = frame[frame["ema"].notna()].groupby(["user_id", "day"])["prompt_idx"].transform("min")
    frame["first_of_day"] = frame["prompt_idx"].eq(first.reindex(frame.index))
    return frame


def run_engine(frame, threshold_quantile=THRESHOLD_QUANTILE, night_break=False):
    """calculate_mssd + apply_decision_rules, unmodified, on one input frame."""
    frame = frame.sort_values(["user_id", "timestamp"]).reset_index(drop=True)
    if night_break:
        starts = frame.groupby(["user_id", "day"], as_index=False)["timestamp"].min()
        starts = starts[starts["day"] > 0]
        breaks = starts.assign(timestamp=starts["timestamp"] - pd.Timedelta(hours=6),
                               ema=np.nan, night_row=True)
        frame = pd.concat([frame.assign(night_row=False), breaks], ignore_index=True)
        mssd = calculate_mssd(frame, window=MSSD_WINDOW)
        mssd = mssd[~mssd["night_row"].astype(bool)].drop(columns="night_row")
    else:
        mssd = calculate_mssd(frame, window=MSSD_WINDOW)
    mssd = _overnight_flags(mssd.reset_index(drop=True))
    out = apply_decision_rules(mssd, threshold_quantile=threshold_quantile,
                               cooldown_minutes=COOLDOWN_MINUTES,
                               max_prompts_per_day=MAX_PROMPTS_PER_DAY)
    out["evaluable"] = (out["ema"].notna() & out["observed_mssd"].notna()
                        & out["user_threshold"].notna())
    out["crossed"] = out["evaluable"] & (out["observed_mssd"] > out["user_threshold"])
    out["tied"] = out["evaluable"] & (out["observed_mssd"] == out["user_threshold"])
    return out


def recovery(out):
    """Per participant: MSSD of the series the engine saw vs its true expected MSSD."""
    rows = []
    for uid, g in out.groupby("user_id"):
        d = g.sort_values("timestamp")["ema"].diff().dropna()
        if len(d) >= 5:
            rows.append((float(g["true_mssd"].iloc[0]), float((d ** 2).mean())))
    t, e = np.array(rows).T
    return stats.pearsonr(t, e).statistic, stats.spearmanr(t, e).statistic


def summarise(out, days, burn_in=RUN_IN_DAYS):
    """The calibration metrics Paper A reports, on decisions after the run-in."""
    post = out[out["day"] >= burn_in]
    ev = post[post["evaluable"]]
    weeks = (days - burn_in) / 7.0
    per_user = post.groupby(["rep", "user_id"])["send_prompt"].sum() / weeks
    rs =[recovery(g) for _, g in out.groupby("rep")]
    ow = ev[ev["overnight_window"]]
    nw = ev[~ev["overnight_window"]]
    return dict(
        eligible_per_week=float(per_user.mean()),
        eligible_per_week_ci=float(1.96 * per_user.std(ddof=1) / np.sqrt(per_user.size)),
        crossing_rate=float(ev["crossed"].mean()),
        tie_rate=float(ev["tied"].mean()),
        crossing_or_tie=float((ev["crossed"] | ev["tied"]).mean()),
        recovery_r=float(np.mean([x[0] for x in rs])),
        recovery_spearman=float(np.mean([x[1] for x in rs])),
        overnight_window_share=float(ev["overnight_window"].mean()),
        crossing_overnight_window=float(ow["crossed"].mean()) if len(ow) else np.nan,
        crossing_daytime_window=float(nw["crossed"].mean()) if len(nw) else np.nan,
        crossing_first_of_day=float(ev.loc[ev["first_of_day"], "crossed"].mean()),
        tpr=_rate(ev, "crossed", "truth_high_vol"),
        fpr=_rate(ev, "crossed", "truth_high_vol", negative=True),
        n_evaluable=int(len(ev)),
    )


def _rate(ev, pred, truth, negative=False):
    t = ev[truth].to_numpy(dtype=bool)
    p = ev[pred].to_numpy(dtype=bool)
    if negative:
        return float(p[~t].mean()) if (~t).any() else np.nan
    return float(p[t].mean()) if t.any() else np.nan


def run_models(models, users=150, days=28, n_reps=10, seed=42, resp_rate=0.80,
               corr=FIELD_ITEM_CORRELATIONS, threshold_quantile=THRESHOLD_QUANTILE):
    """Every model through the engine on n_reps cohorts; one summary row per model."""
    cache, frames = {}, {name: [] for name in models}
    for rep in range(n_reps):
        for name, spec in models.items():
            key = (spec["night"], tuple(spec.get("corr", corr)))
            if key not in cache:
                cache[key] = make_cohort(users, days, seed + rep, resp_rate=resp_rate,
                                         corr=key[1], night=spec["night"])
            frame = engine_input(cache[key], spec["signal"], spec["bridge"])
            out = run_engine(frame, threshold_quantile, spec.get("night_break", False))
            frames[name].append(out.assign(rep=rep))
        cache.clear()
    rows = [dict(model=name, **summarise(pd.concat(fr, ignore_index=True), days))
            for name, fr in frames.items()]
    return pd.DataFrame(rows)


def dosage_grid(spec, threshold_quantiles, burn_in_days, users=150, days=28, n_reps=10,
                seed=42, resp_rate=0.80, corr=FIELD_ITEM_CORRELATIONS):
    """threshold x burn-in grid of eligible decisions per week, for one input model."""
    recs = []
    for rep in range(n_reps):
        cohort = make_cohort(users, days, seed + rep, resp_rate=resp_rate, corr=corr,
                             night=spec["night"])
        frame = engine_input(cohort, spec["signal"], spec["bridge"])
        for tq in threshold_quantiles:
            out = run_engine(frame, tq, spec.get("night_break", False))
            for bd in burn_in_days:
                post = out[out["day"] >= bd]
                ppw = post.groupby("user_id")["send_prompt"].sum() / ((days - bd) / 7.0)
                recs.append(dict(threshold_quantile=tq, burn_in_days=bd,
                                 prompts_per_week=float(ppw.mean())))
    return (pd.DataFrame(recs).groupby(["threshold_quantile", "burn_in_days"])
              ["prompts_per_week"].mean().reset_index())


ROBUST_DAYS = 35
SHIFT_DAY = 14
SCENARIOS = ("stationary", "shift_up", "shift_down", "drift")


def scale_path(kind, n, shift_idx, rng, factor=2.0, phi=0.97, vol_of_vol=0.10):
    """Volatility multiplier applied to all three items at once."""
    if kind == "stationary":
        return np.ones(n)
    if kind == "shift_up":
        return np.where(np.arange(n) >= shift_idx, factor, 1.0)
    if kind == "shift_down":
        return np.where(np.arange(n) >= shift_idx, 1.0 / factor, 1.0)
    if kind == "drift":
        log_s = np.zeros(n)
        e = rng.standard_normal(n)
        for t in range(1, n):
            log_s[t] = phi * log_s[t - 1] + vol_of_vol * e[t]
        return np.clip(np.exp(log_s), 0.4, 2.5)
    raise ValueError(kind)


ROBUST_INPUTS = {
    "A single item (published)": dict(signal="single", bridge=False, night=1),
    "C composite, production": dict(signal="composite", bridge=True, night=4),
}


def run_robustness(inputs=ROBUST_INPUTS, scenarios=SCENARIOS, users=150, n_reps=10,
                   seed=42, resp_rate=0.80, corr=FIELD_ITEM_CORRELATIONS,
                   days=ROBUST_DAYS, shift_day=SHIFT_DAY):
    """Volatility scenarios x input models; paired on participants and innovations.

    The participant draws, innovations and missingness depend only on the seed,
    so within a replication a participant's pre-shift series is identical in
    every scenario; only the multiplier path changes.
    """
    n = days * EMA_PER_DAY
    rows = []
    for name, spec in inputs.items():
        for scen in scenarios:
            outs = []
            for rep in range(n_reps):
                path_rng = np.random.default_rng([seed, rep, 3])
                paths = [scale_path(scen, n, shift_day * EMA_PER_DAY, path_rng) for _ in range(users)]
                cohort = make_cohort(users, days, seed + rep, resp_rate=resp_rate, corr=corr,
                                     night=spec["night"], scale_paths=paths)
                frame = engine_input(cohort, spec["signal"], spec["bridge"])
                outs.append(run_engine(frame).assign(rep=rep))
            out = pd.concat(outs, ignore_index=True)
            rows.append(dict(input=name, scenario=scen, **robust_summary(out, days, shift_day)))
    return pd.DataFrame(rows)


def robust_summary(out, days, shift_day):
    """Detection, dosage before and after the shift, and the late crossing rate."""
    ev = out[out["evaluable"] & (out["day"] >= RUN_IN_DAYS)]
    tp = (ev["crossed"] & ev["truth_high_vol"]).sum()

    def ppw(x, n_days):
        return float((x.groupby(["rep", "user_id"])["send_prompt"].sum() / (n_days / 7.0)).mean())

    pre = out[(out["day"] >= RUN_IN_DAYS) & (out["day"] < shift_day)]
    post = out[out["day"] >= shift_day]
    late = ev[ev["day"] >= days - 7]
    return dict(
        tpr=_rate(ev, "crossed", "truth_high_vol"),
        fpr=_rate(ev, "crossed", "truth_high_vol", negative=True),
        precision=float(tp / ev["crossed"].sum()) if ev["crossed"].any() else np.nan,
        prompts_per_week_pre=ppw(pre, shift_day - RUN_IN_DAYS),
        prompts_per_week_post=ppw(post, days - shift_day),
        crossing_rate_pre=float(ev.loc[ev["day"] < shift_day, "crossed"].mean()),
        crossing_rate_last_week=float(late["crossed"].mean()),
        tie_rate=float(ev["tied"].mean()),
        n_evaluable=int(len(ev)),
    )
