"""
Phase 1 field check for Paper A: the observed MSSD trigger rate against the
design rate, and a description of the real engine input.

READ-ONLY. Every database call is a SELECT through the Django ORM against
whatever database the backend .env points at (production, in practice).
Nothing here writes, recomputes or backfills.

Phase 1 is the first five RS participants by enrolled_at. Rates on five people
are descriptive only; the project's own reporting rule suppresses rates below
10 participants, so every rate is shown with its counts and a Wilson interval.

Outputs (analytics/sensitivity_analysis/outputs/, *.csv is git-ignored because
the per-participant table carries study IDs):
  field_check_participants.csv   one row per participant
  field_check_items.csv          per-participant item parameters for the
                                 composite simulation (sigma, rho, correlations)
  field_check_summary.json       pooled figures quoted in Paper A
  figures/field_check_crossing.png  crossing rate per participant vs design

Run from the repo root:
    python analytics/sensitivity_analysis/field_check.py
    python analytics/sensitivity_analysis/field_check.py --plot-only   # redraw from saved outputs, no DB
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
for _path in (str(REPO), str(REPO / "backend"), str(REPO / "analytics")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

os.chdir(REPO / "backend")

import scripts  # noqa: E402

PHASE_1_SIZE = 5
DESIGN_CROSSING_RATE = 0.20
OUT_DIR = HERE / "outputs"
FIG_DIR = HERE / "figures"


def wilson(successes, n, z=1.96):
    """Wilson score interval for a binomial rate; (nan, nan, nan) when n == 0."""
    if n == 0:
        return math.nan, math.nan, math.nan
    p = successes / n
    denom = 1 + z ** 2 / n
    centre = (p + z ** 2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2)) / denom
    return p, centre - half, centre + half


def phase_1_users():
    from app.models import User

    users = list(
        User.objects.filter(study_id__istartswith="RS", enrolled_at__isnull=False)
        .order_by("enrolled_at")[:PHASE_1_SIZE]
    )
    if len(users) != PHASE_1_SIZE:
        raise RuntimeError(f"expected {PHASE_1_SIZE} Phase 1 participants, found {len(users)}")
    return users


def decision_rows(user):
    """Every logged decision for one participant, with its local study day."""
    from app.models import JITAILog
    from dashboard.data.config import PARTICIPANT_TZ
    from dashboard.data.windows import study_day_for

    rows = pd.DataFrame(
        JITAILog.objects.filter(user=user).values(
            "id", "decision_point_id", "triggered_at", "ema_id", "ema__sent_at",
            "observed_mssd", "threshold_at_decision", "threshold_source",
            "randomization_draw", "randomization_probability", "send_prompt",
            "suppression_reason", "trigger_reason",
        )
    )
    if rows.empty:
        return rows
    rows["local_date"] = rows["triggered_at"].map(lambda t: t.astimezone(PARTICIPANT_TZ).date())
    rows["study_day"] = rows["local_date"].map(lambda d: study_day_for(user, d))
    return rows


def signal_items(user):
    """The three engine items per completed check-in, as build_decision_frame reads them."""
    from app.models import EMA
    from app.tasks import SIGNAL_SUB_ITEMS

    wanted = set(SIGNAL_SUB_ITEMS.values())
    records = []
    for ema in (
        EMA.objects.filter(user=user, status="completed")
        .prefetch_related("item_responses")
        .order_by("sent_at")
    ):
        values = {r.sub_item_id: r.value_numeric for r in ema.item_responses.all() if r.sub_item_id in wanted}
        if wanted <= values.keys():
            records.append({"sent_at": ema.sent_at, "ema_type": ema.ema_type, **values})
    return pd.DataFrame(records)


def describe_input(items):
    """Overnight, bridged-slot and grid properties of one participant's engine input."""
    from dashboard.data.config import PARTICIPANT_TZ
    from dashboard.data.windows import slot_index_for

    if len(items) < 2:
        return {}
    local = items["sent_at"].map(lambda t: t.astimezone(PARTICIPANT_TZ))
    dates = local.map(lambda t: t.date())
    slots = items["sent_at"].map(slot_index_for)
    composite = items[["B1_valence", "B2_stress", "B1_arousal"]].mean(axis=1)

    overnight = (dates.values[1:] != dates.values[:-1])
    same_day = ~overnight
    slot_prev, slot_next = slots.values[:-1], slots.values[1:]
    skipped = np.array([
        same and a is not None and b is not None and b - a > 1
        for same, a, b in zip(same_day, slot_prev, slot_next)
    ])

    diffs = items[["B1_valence", "B2_stress", "B1_arousal"]].diff().iloc[1:]
    level_corr = items[["B1_valence", "B2_stress", "B1_arousal"]].corr()
    diff_corr = diffs.corr()

    windows = pd.Series(overnight.astype(float)).rolling(3, min_periods=1).max()

    return {
        "n_inputs": len(items),
        "share_non_scheduled": float((items["ema_type"] != "scheduled_check_in").mean()),
        "share_diffs_overnight": float(overnight.mean()),
        "share_windows_with_overnight": float(windows.mean()),
        "share_same_day_diffs_skipping_slot": float(skipped[same_day].mean()) if same_day.any() else math.nan,
        "share_composite_off_integer": float((np.abs(composite - composite.round()) > 1e-9).mean()),
        "corr_valence_stress": float(level_corr.loc["B1_valence", "B2_stress"]),
        "corr_valence_arousal": float(level_corr.loc["B1_valence", "B1_arousal"]),
        "corr_stress_arousal": float(level_corr.loc["B2_stress", "B1_arousal"]),
        "diffcorr_valence_stress": float(diff_corr.loc["B1_valence", "B2_stress"]),
        "diffcorr_valence_arousal": float(diff_corr.loc["B1_valence", "B1_arousal"]),
        "diffcorr_stress_arousal": float(diff_corr.loc["B2_stress", "B1_arousal"]),
    }


def item_parameters(items):
    """Per-item SD and lag-1 autocorrelation over consecutive completed check-ins."""
    out = {}
    for column in ("B1_valence", "B2_stress", "B1_arousal"):
        series = items[column].astype(float)
        out[f"sd_{column}"] = float(series.std(ddof=1)) if len(series) > 1 else math.nan
        out[f"rho_{column}"] = float(series.autocorr(lag=1)) if len(series) > 2 else math.nan
    composite = items[["B1_valence", "B2_stress", "B1_arousal"]].mean(axis=1)
    out["sd_composite"] = float(composite.std(ddof=1)) if len(composite) > 1 else math.nan
    out["rho_composite"] = float(composite.autocorr(lag=1)) if len(composite) > 2 else math.nan
    return out


def window_flags(user):
    """Per engine input: does its 3-difference window hold an overnight difference?"""
    from app.tasks import build_decision_frame
    from dashboard.data.config import PARTICIPANT_TZ

    frame = build_decision_frame(user)
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["timestamp", "overnight_window", "first_of_day"])
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    dates = frame["timestamp"].map(lambda t: t.astimezone(PARTICIPANT_TZ).date())
    crosses = (dates != dates.shift(1)) & dates.shift(1).notna()
    return pd.DataFrame({
        "timestamp": frame["timestamp"],
        "overnight_window": crosses.astype(float).rolling(3, min_periods=1).max().astype(bool),
        "first_of_day": crosses,
    })


def replay_check(user, rows):
    """Re-run build_decision_frame in memory and compare it with the logged engine values."""
    from app.tasks import build_decision_frame

    frame = build_decision_frame(user)
    engine = rows[(rows["threshold_source"] == "engine") & rows["ema__sent_at"].notna()]
    if frame is None or engine.empty:
        return {"replay_rows": 0, "replay_mssd_match": math.nan, "replay_threshold_match": math.nan}
    merged = engine.merge(
        frame[["timestamp", "observed_mssd", "user_threshold"]],
        left_on="ema__sent_at", right_on="timestamp", how="left",
        suffixes=("_logged", "_replay"),
    )

    def same(a, b):
        both_nan = a.isna() & b.isna()
        close = np.isclose(a.astype(float), b.astype(float), atol=1e-9, equal_nan=False)
        return both_nan | close

    return {
        "replay_rows": len(merged),
        "replay_mssd_match": float(same(merged["observed_mssd_logged"], merged["observed_mssd_replay"]).mean()),
        "replay_threshold_match": float(same(merged["threshold_at_decision"], merged["user_threshold"]).mean()),
    }


def participant_summary(index, user, rows, items):
    from dashboard.data.config import RUN_IN_DAYS

    mrt = rows[rows["study_day"].notna() & (rows["study_day"] >= RUN_IN_DAYS)]
    evaluable = mrt[
        mrt["observed_mssd"].notna()
        & mrt["threshold_at_decision"].notna()
        & (mrt["threshold_source"] == "engine")
    ]
    crossed = evaluable["observed_mssd"] > evaluable["threshold_at_decision"]
    ties = np.isclose(evaluable["observed_mssd"], evaluable["threshold_at_decision"])
    randomized = mrt["randomization_draw"].notna()
    sent = mrt["send_prompt"].fillna(False).astype(bool)
    mrt_days = (mrt["local_date"].max() - mrt["local_date"].min()).days + 1 if not mrt.empty else 0

    crossing = wilson(int(crossed.sum()), len(evaluable))
    availability = wilson(int(randomized.sum()), len(mrt))

    flagged = evaluable.assign(crossed=crossed).merge(
        window_flags(user), left_on="ema__sent_at", right_on="timestamp", how="left")
    night = flagged["overnight_window"].fillna(False).astype(bool)
    first = flagged["first_of_day"].fillna(False).astype(bool)

    return {
        "participant": f"P{index + 1}",
        "study_id": user.study_id,
        "enrolled_at": user.enrolled_at.isoformat(),
        "decisions_total": len(rows),
        "decisions_mrt": len(mrt),
        "mrt_days_observed": mrt_days,
        "evaluable_mrt": len(evaluable),
        "crossings_mrt": int(crossed.sum()),
        "crossing_rate": crossing[0],
        "crossing_ci_low": crossing[1],
        "crossing_ci_high": crossing[2],
        "ties_mrt": int(ties.sum()),
        "tie_rate": float(ties.mean()) if len(evaluable) else math.nan,
        "randomized_mrt": int(randomized.sum()),
        "availability": availability[0],
        "availability_ci_low": availability[1],
        "availability_ci_high": availability[2],
        "sent_mrt": int(sent.sum()),
        "evaluable_overnight_window": int(night.sum()),
        "crossings_overnight_window": int(flagged.loc[night, "crossed"].sum()),
        "evaluable_daytime_window": int((~night).sum()),
        "crossings_daytime_window": int(flagged.loc[~night, "crossed"].sum()),
        "evaluable_first_of_day": int(first.sum()),
        "crossings_first_of_day": int(flagged.loc[first, "crossed"].sum()),
        "crossings_per_week": crossed.sum() / mrt_days * 7 if mrt_days else math.nan,
        "sent_per_day": sent.sum() / mrt_days if mrt_days else math.nan,
        **describe_input(items),
        **replay_check(user, rows),
    }


def plot_crossing(table, pooled_rate):
    """Crossing rate per participant against the design rate and the composite simulation."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 3.6))
    x = np.arange(len(table))
    ax.errorbar(
        x, table["crossing_rate"],
        yerr=[table["crossing_rate"] - table["crossing_ci_low"], table["crossing_ci_high"] - table["crossing_rate"]],
        fmt="o", color="#2b5d8a", capsize=3, label="observed (95% Wilson)",
    )
    ax.axhline(DESIGN_CROSSING_RATE, color="#b5463c", ls="--", lw=1, label="design rate (0.20)")
    ax.axhline(pooled_rate, color="#555555", ls=":", lw=1, label=f"Phase 1 pooled ({pooled_rate:.2f})")
    simulated = OUT_DIR / "composite_calibration.csv"
    if simulated.exists():
        sim = pd.read_csv(simulated).set_index("model")["crossing_rate"]
        model = "C composite, production"
        if model in sim:
            ax.axhline(sim[model], color="#3c8c5a", ls="-.", lw=1,
                       label=f"simulated, production composite ({sim[model]:.2f})")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{p}\n(n={n})" for p, n in zip(table["participant"], table["evaluable_mrt"])])
    ax.set_ylabel("threshold-crossing rate\n(evaluable MRT decisions)")
    ax.set_ylim(0, max(0.6, float(table["crossing_ci_high"].max()) + 0.05))
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "field_check_crossing.png", dpi=200)


def main():
    scripts._ensure_django()
    from dashboard.data.config import AVAILABILITY_PLANNED

    OUT_DIR.mkdir(exist_ok=True)
    FIG_DIR.mkdir(exist_ok=True)

    users = phase_1_users()
    summaries, parameters = [], []
    for index, user in enumerate(users):
        rows = decision_rows(user)
        items = signal_items(user)
        summaries.append(participant_summary(index, user, rows, items))
        parameters.append({"participant": f"P{index + 1}", **item_parameters(items)})
        print(f"  {user.study_id}: {len(rows)} decisions, {len(items)} engine inputs")

    table = pd.DataFrame(summaries)
    params = pd.DataFrame(parameters)
    table.to_csv(OUT_DIR / "field_check_participants.csv", index=False)
    params.to_csv(OUT_DIR / "field_check_items.csv", index=False)

    crossing = wilson(int(table["crossings_mrt"].sum()), int(table["evaluable_mrt"].sum()))
    availability = wilson(int(table["randomized_mrt"].sum()), int(table["decisions_mrt"].sum()))
    window_rates = {}
    for label in ("overnight_window", "daytime_window", "first_of_day"):
        rate = wilson(int(table[f"crossings_{label}"].sum()), int(table[f"evaluable_{label}"].sum()))
        window_rates[f"evaluable_{label}"] = int(table[f"evaluable_{label}"].sum())
        window_rates[f"crossing_rate_{label}"] = rate[0]
        window_rates[f"crossing_ci_{label}"] = [rate[1], rate[2]]
    pooled = {
        "participants": len(table),
        "decisions_mrt": int(table["decisions_mrt"].sum()),
        "evaluable_mrt": int(table["evaluable_mrt"].sum()),
        "crossings_mrt": int(table["crossings_mrt"].sum()),
        "crossing_rate": crossing[0],
        "crossing_ci": [crossing[1], crossing[2]],
        "design_crossing_rate": DESIGN_CROSSING_RATE,
        "tie_rate": float(table["ties_mrt"].sum() / table["evaluable_mrt"].sum()),
        **window_rates,
        "randomized_mrt": int(table["randomized_mrt"].sum()),
        "availability": availability[0],
        "availability_ci": [availability[1], availability[2]],
        "availability_planned": AVAILABILITY_PLANNED,
        "crossings_per_week_mean": float(table["crossings_per_week"].mean()),
        "sent_per_day_mean": float(table["sent_per_day"].mean()),
        "share_diffs_overnight_mean": float(table["share_diffs_overnight"].mean()),
        "share_windows_with_overnight_mean": float(table["share_windows_with_overnight"].mean()),
        "share_same_day_diffs_skipping_slot_mean": float(table["share_same_day_diffs_skipping_slot"].mean()),
        "share_non_scheduled_mean": float(table["share_non_scheduled"].mean()),
        "share_composite_off_integer_mean": float(table["share_composite_off_integer"].mean()),
        "corr_valence_stress_mean": float(table["corr_valence_stress"].mean()),
        "corr_valence_arousal_mean": float(table["corr_valence_arousal"].mean()),
        "corr_stress_arousal_mean": float(table["corr_stress_arousal"].mean()),
        "item_sd_mean": float(params[["sd_B1_valence", "sd_B2_stress", "sd_B1_arousal"]].stack().mean()),
        "item_rho_mean": float(params[["rho_B1_valence", "rho_B2_stress", "rho_B1_arousal"]].stack().mean()),
        "replay_rows": int(table["replay_rows"].sum()),
        "replay_mssd_match": float(np.average(table["replay_mssd_match"].fillna(0), weights=table["replay_rows"].clip(lower=1))),
        "replay_threshold_match": float(np.average(table["replay_threshold_match"].fillna(0), weights=table["replay_rows"].clip(lower=1))),
    }
    (OUT_DIR / "field_check_summary.json").write_text(json.dumps(pooled, indent=2, default=float))

    plot_crossing(table, crossing[0])

    print(json.dumps(pooled, indent=2, default=float))


if __name__ == "__main__":
    if "--plot-only" in sys.argv:
        saved = pd.read_csv(OUT_DIR / "field_check_participants.csv")
        pooled = json.loads((OUT_DIR / "field_check_summary.json").read_text())
        plot_crossing(saved, pooled["crossing_rate"])
    else:
        main()
