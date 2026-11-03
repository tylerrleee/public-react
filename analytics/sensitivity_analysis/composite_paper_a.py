"""
Paper A simulations, rerun on the production composite input.

Every analysis Paper A reports is recomputed here with the engine input that
production uses (backend/app/tasks.py::build_decision_frame): the raw mean of
B1_valence, B2_stress and B1_arousal per completed check-in, missed prompts
spanned, and a 12-hour night (4 latent steps at the 3-hour prompt spacing),
with between-item correlations at the Phase 1 field means. The engine itself
(calculate_mssd / apply_decision_rules) is unmodified.

Sections (run all, or one with --only):
    calibration   threshold x burn-in grid at 70/80/90% response
    recovery      decision-log cohort: MSSD, sigma and rho recovery, eligibility shares
    sweep         recovery against response rate (regression + ANOVA)
    grid          controlled sigma x rho grid
    robustness    volatility scenarios x {expanding, rolling} thresholds, oracle tracking

Composite sigma and rho are the composite's own stationary SD and within-day
lag-1 autocorrelation, derived from the three-item VAR(1):
    sigma_c^2 = w' Sigma w,   rho_c = 1 - E / (2 sigma_c^2),  E = expected MSSD.

Outputs: outputs/composite_paper_a/*.csv|json, figures/composite/*.png
"""

import argparse
import json
import os
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

import composite_check as cc
from decision_engine.decision_engine import calculate_mssd
from mssd_validation import recover_ar1_params
from synthetic_generator import generate_user_composite

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "outputs", "composite_paper_a")
FIG = os.path.join(HERE, "figures", "composite")
SEED = 42
PROD = cc.MODELS["C composite, production"]
NIGHT = PROD["night"]
THRESHOLD_QUANTILES = [0.70, 0.75, 0.80, 0.85, 0.90]
BURN_IN_DAYS = [0, 1, 2, 3, 5, 7]
RESP_RATES = [0.70, 0.80, 0.90]
RANDOMIZATION_P = 0.50


def save_json(name, obj):
    with open(os.path.join(OUT, name), "w") as f:
        json.dump(obj, f, indent=2, default=float)


def composite_truth(cohort):
    """Per participant: composite sigma, within-day rho and expected MSSD."""
    first = cohort.groupby("user_id").first()
    sigma_c = first["true_sigma_composite"]
    expected = first["true_expected_mssd"]
    return pd.DataFrame({"true_sigma": sigma_c, "true_rho": 1.0 - expected / (2.0 * sigma_c ** 2),
                         "true_expected_mssd": expected})


def bridged_mssd(series):
    """MSSD of the series the engine sees: answered check-ins only, gaps spanned."""
    x = np.asarray(series, dtype=float)
    x = x[~np.isnan(x)]
    return float(np.mean(np.diff(x) ** 2)) if x.size > 2 else np.nan


def per_user_recovery(cohort):
    truth = composite_truth(cohort)
    rows = []
    for uid, g in cohort.groupby("user_id"):
        ema = g.sort_values("prompt_idx")["ema"].to_numpy(dtype=float)
        rho_hat, sigma_hat = recover_ar1_params(ema)
        rows.append({"user_id": uid, "empirical_mssd": bridged_mssd(ema), "rho_hat": rho_hat,
                     "sigma_hat": sigma_hat, "n_answered": int(np.sum(~np.isnan(ema))),
                     "n_total": int(ema.size)})
    out = pd.DataFrame(rows).set_index("user_id").join(truth).reset_index()
    out["resp_rate"] = out["n_answered"] / out["n_total"]
    return out


# ---------------------------------------------------------------- calibration
def draw_heatmap(ax, mat, title, vmin, vmax):
    im = ax.imshow(mat.to_numpy(), aspect="auto", origin="lower", cmap="cividis", vmin=vmin, vmax=vmax)
    ax.set_xticks(range(mat.shape[1])); ax.set_xticklabels(mat.columns)
    ax.set_yticks(range(mat.shape[0])); ax.set_yticklabels([f"{q:.0%}" for q in mat.index])
    ax.set_xlabel("burn-in length (warm-up days, no prompts)")
    ax.set_title(title, fontsize=10, fontweight="bold")
    cut = vmax * 0.6
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            v = mat.iat[i, j]
            ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=8,
                    color="white" if v < cut else "black")
    return im


def run_calibration():
    grids = {}
    for rr in RESP_RATES:
        g = cc.dosage_grid(PROD, THRESHOLD_QUANTILES, BURN_IN_DAYS, users=150, days=28,
                           n_reps=10, seed=SEED, resp_rate=rr)
        grids[rr] = g.pivot(index="threshold_quantile", columns="burn_in_days", values="prompts_per_week")
    tidy = pd.concat([g.stack().rename("prompts_per_week").reset_index().assign(resp_rate=rr)
                      for rr, g in grids.items()])
    tidy.to_csv(os.path.join(OUT, "calibration_grid.csv"), index=False)

    main = grids[0.80]
    fig, ax = plt.subplots(figsize=(10, 5))
    im = draw_heatmap(ax, main, "Eligible decision points / participant / week, production composite\n"
                      "(MSSD threshold percentile x burn-in, resp_rate = 80%, n = 1500)",
                      main.values.min(), main.values.max())
    ax.set_ylabel("MSSD threshold percentile")
    fig.colorbar(im, ax=ax, label="eligible decision points / participant / week")
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "threshold_sensitivity_grid.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)

    vmin = min(g.values.min() for g in grids.values()); vmax = max(g.values.max() for g in grids.values())
    fig, axes = plt.subplots(1, 3, figsize=(18, 5), sharey=True)
    for ax, rr in zip(axes, RESP_RATES):
        im = draw_heatmap(ax, grids[rr], f"resp_rate = {rr:.0%}", vmin, vmax)
    axes[0].set_ylabel("MSSD threshold percentile")
    fig.colorbar(im, ax=axes, label="eligible decision points / participant / week")
    fig.suptitle("Eligible decision points by threshold percentile and burn-in, production composite",
                 fontsize=12, fontweight="bold")
    fig.savefig(os.path.join(FIG, "threshold_sensitivity_grid_by_resprate.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)

    summary = {
        "grid_80_burnin7": {f"{q:.2f}": float(main.loc[q, 7]) for q in THRESHOLD_QUANTILES},
        "p80_burnin0": float(main.loc[0.80, 0]), "p80_burnin3": float(main.loc[0.80, 3]),
        "p80_burnin7_by_resp": {f"{rr:.2f}": float(g.loc[0.80, 7]) for rr, g in grids.items()},
        "burnin_drop_0_to_7": {f"{q:.2f}": float(main.loc[q, 0] - main.loc[q, 7]) for q in THRESHOLD_QUANTILES},
    }
    save_json("calibration_summary.json", summary)
    print(json.dumps(summary, indent=1))


# ---------------------------------------------------------------- recovery (decision-log cohort)
def recovery_cohort(users=100, days=7, seed=SEED):
    frames = []
    for i in range(users):
        c = cc.make_cohort(1, days, seed + i, resp_rate=0.65 + (i % 8) * 0.04, night=NIGHT, prefix=f"p{i:03d}_")
        frames.append(c)
    return pd.concat(frames, ignore_index=True)


def fig_param_recovery(df, path, title):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.8))
    for ax, param, other, cmap in ((axes[0], "sigma", "rho", "viridis"), (axes[1], "rho", "sigma", "plasma")):
        t, h = df[f"true_{param}"], df[f"{param}_hat"]
        sc = ax.scatter(t, h, c=df[f"true_{other}"], cmap=cmap, s=50, alpha=0.75, edgecolor="white")
        lo, hi = min(t.min(), h.min()), max(t.max(), h.max())
        ax.plot([lo, hi], [lo, hi], "k--", alpha=0.6, label="perfect recovery")
        ax.set_xlabel(f"True composite $\\{param}$"); ax.set_ylabel(f"Recovered $\\hat{{\\{param}}}$")
        ax.set_title(f"$\\{param}$ recovery (r = {stats.pearsonr(t, h).statistic:.3f})")
        ax.grid(True, ls="--", alpha=0.3); ax.legend(loc="upper left", fontsize=8)
        fig.colorbar(sc, ax=ax, label=f"true composite $\\{other}$")
    fig.suptitle(title); fig.tight_layout(); fig.savefig(path, dpi=150, bbox_inches="tight"); plt.close(fig)


def fig_mssd_recovery(df, path, title):
    x, y = df["true_expected_mssd"].to_numpy(), df["empirical_mssd"].to_numpy()
    fit = stats.linregress(x, y)
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.scatter(x, y, s=30, alpha=0.6, color="tab:blue", edgecolor="white")
    xs = np.linspace(x.min(), x.max(), 100)
    ax.plot(xs, fit.slope * xs + fit.intercept, color="black", lw=2.5,
            label=f"OLS: y = {fit.slope:.2f}x + {fit.intercept:.3f}")
    ax.annotate(f"Pearson r = {fit.rvalue:.3f}\nSpearman ρ = {stats.spearmanr(x, y).statistic:.3f}",
                xy=(0.04, 0.85), xycoords="axes fraction", bbox=dict(boxstyle="round", fc="white", ec="0.7"))
    ax.set_xlabel(r"True expected composite MSSD: $2\mathbf{w}^\top(\Sigma-\Gamma_1)\mathbf{w}$")
    ax.set_ylabel("Empirical MSSD of the engine input (gaps spanned, overnight included)")
    ax.set_title(title); ax.grid(True, ls="--", alpha=0.3); ax.legend(loc="lower right")
    fig.tight_layout(); fig.savefig(path, dpi=150, bbox_inches="tight"); plt.close(fig)


def recovery_by_bin(df, bins):
    out = []
    for b, g in df.groupby(bins, observed=True):
        row = {"mid": b.mid, "n": len(g)}
        for label, t, h in (("MSSD", "true_expected_mssd", "empirical_mssd"), ("ρ", "true_rho", "rho_hat"),
                            ("σ", "true_sigma", "sigma_hat")):
            row[label] = stats.pearsonr(g[t], g[h]).statistic if len(g) >= 3 else np.nan
        out.append(row)
    return pd.DataFrame(out)


def run_recovery():
    cohort = recovery_cohort()
    frame = cc.engine_input(cohort, PROD["signal"], PROD["bridge"])
    dec = cc.run_engine(frame)
    rec = per_user_recovery(cohort)
    dl = rec[rec["n_answered"] >= 10].dropna(subset=["empirical_mssd", "rho_hat", "sigma_hat"]).reset_index(drop=True)
    dl.to_csv(os.path.join(OUT, "recovery_decision_log.csv"), index=False)
    fit = stats.linregress(dl["true_expected_mssd"], dl["empirical_mssd"])
    ev = dec[dec["evaluable"]]
    summary = {
        "n_participants": int(len(rec)), "n_analysed": int(len(dl)),
        "realised_resp_mean": float(rec["resp_rate"].mean()),
        "mssd_r": float(fit.rvalue), "mssd_spearman": float(stats.spearmanr(dl["true_expected_mssd"], dl["empirical_mssd"]).statistic),
        "mssd_slope": float(fit.slope),
        "empirical_mean": float(dl["empirical_mssd"].mean()), "empirical_sd": float(dl["empirical_mssd"].std()),
        "true_mean": float(dl["true_expected_mssd"].mean()), "true_sd": float(dl["true_expected_mssd"].std()),
        "sigma_r": float(stats.pearsonr(dl["true_sigma"], dl["sigma_hat"]).statistic),
        "rho_r": float(stats.pearsonr(dl["true_rho"], dl["rho_hat"]).statistic),
        "eligible_share_all_prompts": float(dec["send_prompt"].sum() / len(cohort)),
        "crossing_share_evaluable": float(ev["crossed"].mean()),
        "tie_share_evaluable": float(ev["tied"].mean()),
    }
    save_json("recovery_summary.json", summary)
    fig_param_recovery(dl, os.path.join(FIG, "param_recovery_decision_log.png"),
                       f"Parameter recovery, production composite (decision-log cohort, n = {len(dl)})")
    fig_mssd_recovery(dl, os.path.join(FIG, "mssd_recovery_decision_log.png"),
                      f"MSSD recovery, production composite (decision-log cohort, n = {len(dl)})")

    by_rate = recovery_by_bin(dl, pd.cut(dl["resp_rate"], [0.2, 0.4, 0.6, 0.8, 1.0], include_lowest=True))
    by_obs = recovery_by_bin(dl, pd.cut(dl["n_answered"], 5))
    fig, axes = plt.subplots(3, 2, figsize=(16, 10))
    for i, label in enumerate(("MSSD", "ρ", "σ")):
        for j, (tab, color, xname) in enumerate(((by_rate, "tab:blue", "Response Rate"),
                                                 (by_obs, "tab:red", "Answered Check-ins"))):
            ax = axes[i, j]
            ax.plot(tab["mid"], tab[label], marker="o", color=color, lw=2.5, ms=8, markerfacecolor="white")
            for xm, yv, n in zip(tab["mid"], tab[label], tab["n"]):
                if np.isfinite(yv):
                    ax.annotate(f"n={n}", (xm, yv), textcoords="offset points", xytext=(0, 5),
                                ha="center", fontsize=7, color="0.3")
            ax.axhline(0.7, color="green", ls="--", alpha=0.5); ax.axhline(0.5, color="orange", ls="--", alpha=0.5)
            ax.set_ylim(min(0.0, np.nanmin(tab[label]) - 0.05), 1.0); ax.grid(True, ls="--", alpha=0.3)
            ax.set_title(f"{label} recovery by {xname}", fontweight="bold", fontsize=10)
            if j == 0:
                ax.set_ylabel("Pearson r")
    axes[2, 0].set_xlabel("Response rate"); axes[2, 1].set_xlabel("Answered check-ins")
    fig.suptitle(f"Recovery by data availability, production composite (n = {len(dl)})", fontsize=13, fontweight="bold")
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "recovery_by_data_availability.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(json.dumps(summary, indent=1))


# ---------------------------------------------------------------- response-rate sweep
def run_sweep(levels=np.round(np.arange(0.50, 0.96, 0.05), 2), users=200, days=14):
    frames = []
    for k, rr in enumerate(levels):
        cohort = cc.make_cohort(users, days, SEED + 1000 + k, resp_rate=rr, night=NIGHT)
        frames.append(per_user_recovery(cohort).assign(level=rr))
    df = pd.concat(frames, ignore_index=True)
    df["abs_err_sigma"] = (df["sigma_hat"] - df["true_sigma"]).abs()
    df["abs_err_rho"] = (df["rho_hat"] - df["true_rho"]).abs()
    df.to_csv(os.path.join(OUT, "sweep_per_user.csv"), index=False)

    def ci(x):
        x = np.asarray(x, float); x = x[~np.isnan(x)]
        return 1.96 * x.std(ddof=1) / np.sqrt(x.size)

    rows = []
    for rr, g in df.groupby("level"):
        s = g.dropna(subset=["empirical_mssd"])
        rows.append({"resp_rate": rr, "n": len(g), "err_sigma": g["abs_err_sigma"].mean(), "ci_sigma": ci(g["abs_err_sigma"]),
                     "err_rho": g["abs_err_rho"].mean(), "ci_rho": ci(g["abs_err_rho"]),
                     "mssd_r": stats.pearsonr(s["true_expected_mssd"], s["empirical_mssd"]).statistic})
    lv = pd.DataFrame(rows)
    lv.to_csv(os.path.join(OUT, "sweep_by_level.csv"), index=False)
    vs, vr = df.dropna(subset=["abs_err_sigma"]), df.dropna(subset=["abs_err_rho"])
    reg_s, reg_r = stats.linregress(vs["level"], vs["abs_err_sigma"]), stats.linregress(vr["level"], vr["abs_err_rho"])
    reg_m = stats.linregress(lv["resp_rate"], lv["mssd_r"])
    an_s = stats.f_oneway(*[g["abs_err_sigma"].dropna() for _, g in df.groupby("level")])
    an_r = stats.f_oneway(*[g["abs_err_rho"].dropna() for _, g in df.groupby("level")])
    summary = {
        "sigma_slope": reg_s.slope, "sigma_p": reg_s.pvalue, "sigma_anova_F": an_s.statistic, "sigma_anova_p": an_s.pvalue,
        "rho_slope": reg_r.slope, "rho_p": reg_r.pvalue, "rho_anova_F": an_r.statistic, "rho_anova_p": an_r.pvalue,
        "mssd_r_slope": reg_m.slope, "mssd_r_p": reg_m.pvalue,
        "levels": lv.round(4).to_dict(orient="records"),
    }
    save_json("sweep_summary.json", summary)

    fig, axes = plt.subplots(1, 3, figsize=(16, 4.5))
    for ax, col, cicol, reg, title, yl in ((axes[0], "err_sigma", "ci_sigma", reg_s, "σ recovery error", "mean |σ̂ − σ|"),
                                           (axes[1], "err_rho", "ci_rho", reg_r, "ρ recovery error", "mean |ρ̂ − ρ|")):
        x, y, c = lv["resp_rate"], lv[col], lv[cicol]
        ax.plot(x, y, "o-", color="tab:blue", markerfacecolor="white"); ax.fill_between(x, y - c, y + c, alpha=0.2)
        ax.set_title(title, fontweight="bold"); ax.set_xlabel("response rate"); ax.set_ylabel(yl + " (±95% CI)")
        ax.annotate(f"slope={reg.slope:.3f}\np={reg.pvalue:.1e}", xy=(0.05, 0.05), xycoords="axes fraction",
                    bbox=dict(boxstyle="round", fc="white", ec="0.7"), fontsize=9)
        ax.grid(True, ls="--", alpha=0.4)
    axes[2].plot(lv["resp_rate"], lv["mssd_r"], "s-", color="tab:green", markerfacecolor="white")
    axes[2].axhline(0.7, color="green", ls="--", alpha=0.5); axes[2].set_ylim(0, 1)
    axes[2].set_title("MSSD signal strength", fontweight="bold"); axes[2].set_xlabel("response rate")
    axes[2].set_ylabel("MSSD Pearson r"); axes[2].grid(True, ls="--", alpha=0.4)
    fig.suptitle("Response rate vs. composite parameter recovery and MSSD signal", fontsize=13, fontweight="bold")
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "recovery_vs_response_rate.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(json.dumps({k: v for k, v in summary.items() if k != "levels"}, indent=1, default=float))
    print(lv.round(3).to_string(index=False))


# ---------------------------------------------------------------- controlled grid
def run_grid(sigmas=(0.3, 0.6, 0.9, 1.2, 1.5), rhos=(0.2, 0.5, 0.8), per_cell=12, days=14):
    frames, cell = [], 0
    for s in sigmas:
        for r in rhos:
            cell += 1
            cohort = cc.make_cohort(per_cell, days, 7 + cell, resp_rate=0.80, night=NIGHT,
                                    mu=4.0, sigma=s, rho=r, prefix=f"g{cell:02d}_")
            frames.append(per_user_recovery(cohort).assign(item_sigma=s, item_rho=r))
    df = pd.concat(frames, ignore_index=True).dropna(subset=["empirical_mssd"])
    df.to_csv(os.path.join(OUT, "controlled_grid.csv"), index=False)
    fit = stats.linregress(df["true_expected_mssd"], df["empirical_mssd"])
    summary = {"n": int(len(df)), "r": fit.rvalue, "slope": fit.slope,
               "spearman": stats.spearmanr(df["true_expected_mssd"], df["empirical_mssd"]).statistic}
    save_json("controlled_grid_summary.json", summary)
    print(json.dumps(summary, indent=1, default=float))


# ---------------------------------------------------------------- robustness
ROLLING_WINDOW = 35
DAYS, SHIFT_DAY, USERS, N_REPS = 35, 14, 150, 10
SCENARIOS = ["stationary", "shift_up", "shift_down", "drift"]
ARMS = ["expanding", "rolling"]


def apply_gate(df, cooldown_minutes=cc.COOLDOWN_MINUTES, max_prompts_per_day=cc.MAX_PROMPTS_PER_DAY):
    """apply_decision_rules with user_threshold taken as given (copied from robustness_misspecification.ipynb)."""
    df = df.copy().sort_values(["user_id", "timestamp"])
    df["send_prompt"] = False
    df["decision_reason"] = "below within-person threshold"
    for user_id in df["user_id"].unique():
        user_df = df[df["user_id"] == user_id]
        last_prompt_time, prompts_by_day = None, {}
        for idx, row in user_df.iterrows():
            if pd.isna(row["ema"]) or pd.isna(row["observed_mssd"]):
                df.at[idx, "decision_reason"] = "missing or insufficient EMA data"
            elif pd.isna(row["user_threshold"]):
                df.at[idx, "decision_reason"] = "insufficient within-person history"
            elif row["observed_mssd"] <= row["user_threshold"]:
                df.at[idx, "decision_reason"] = "below within-person threshold"
            else:
                day = row["timestamp"].date()
                prompts_by_day.setdefault(day, 0)
                if prompts_by_day[day] >= max_prompts_per_day:
                    df.at[idx, "decision_reason"] = "daily cap reached"
                elif last_prompt_time is not None and (
                        row["timestamp"] - last_prompt_time).total_seconds() / 60 < cooldown_minutes:
                    df.at[idx, "decision_reason"] = "cooldown active"
                else:
                    df.at[idx, "decision_reason"] = "prompt sent"
                    last_prompt_time = row["timestamp"]
                    prompts_by_day[day] += 1
    df["send_prompt"] = df["decision_reason"] == "prompt sent"
    return df


def run_arm(frame, arm):
    if arm == "expanding":
        return cc.run_engine(frame)
    frame = frame.sort_values(["user_id", "timestamp"]).reset_index(drop=True)
    m = cc._overnight_flags(calculate_mssd(frame, window=cc.MSSD_WINDOW).reset_index(drop=True))
    m["user_threshold"] = (m.groupby("user_id")["observed_mssd"]
                           .transform(lambda s: s.rolling(ROLLING_WINDOW, min_periods=3)
                                      .quantile(cc.THRESHOLD_QUANTILE).shift(1)))
    out = apply_gate(m)
    out["evaluable"] = out["ema"].notna() & out["observed_mssd"].notna() & out["user_threshold"].notna()
    out["crossed"] = out["evaluable"] & (out["observed_mssd"] > out["user_threshold"])
    out["tied"] = out["evaluable"] & (out["observed_mssd"] == out["user_threshold"])
    return out


def build_oracle_map(n_users=900, days=60, seed=SEED + 900, n_bins=30):
    """Converged production threshold as a function of true composite expected MSSD.

    Item volatility is drawn log-uniform over 0.075-5.0 so the map covers both a
    halved and a doubled robustness population; outside its range the map is
    flat, which would clamp the oracle and fake a re-adaptation.
    """
    rng = np.random.default_rng([seed, 1])
    frames = []
    for i in range(n_users):
        sig = np.exp(rng.uniform(np.log(0.075), np.log(5.0), 3))
        rho = rng.uniform(0.2, 0.8, 3)
        g = generate_user_composite(f"o{i:04d}", days, cc.EMA_PER_DAY, np.random.default_rng([seed, i]),
                                    overnight_steps=NIGHT - 1, sigma=sig, rho=rho)
        frames.append(g)
    cal = cc.spread_timestamps(pd.concat(frames, ignore_index=True))
    dec = cc.run_engine(cc.engine_input(cal, PROD["signal"], PROD["bridge"]))
    conv = dec[(dec["day"] >= days // 2) & dec["user_threshold"].notna()]
    per_user = conv.groupby("user_id").agg(m=("true_mssd", "first"), threshold=("user_threshold", "median")).dropna()
    edges = np.quantile(per_user["m"], np.linspace(0, 1, n_bins + 1))
    edges[0], edges[-1] = 0.0, np.inf
    per_user["bin"] = pd.cut(per_user["m"], edges, labels=False, include_lowest=True)
    tab = (per_user.groupby("bin").agg(m=("m", "median"), threshold=("threshold", "median"))
           .dropna().sort_values("m").reset_index(drop=True))
    tab["threshold"] = np.maximum.accumulate(tab["threshold"].to_numpy())
    return tab


def detection(g):
    e = g[g["evaluable"]]
    t, p = e["truth_high_vol"].to_numpy(bool), e["crossed"].to_numpy(bool)
    tp, fp, fn, tn = (t & p).sum(), (~t & p).sum(), (t & ~p).sum(), (~t & ~p).sum()
    return dict(tpr=tp / (tp + fn), fpr=fp / (fp + tn), precision=tp / (tp + fp) if tp + fp else np.nan)


def days_to_readapt(day_df, scen, arm, tol=0.25, smooth=3):
    """Ported unchanged from robustness_misspecification.ipynb."""
    s = day_df[(day_df["scenario"] == scen) & (day_df["arm"] == arm)].sort_values("day")
    ratio = s.set_index("day")["tracking_ratio_med"].rolling(smooth, center=True, min_periods=1).median()
    post = ratio.loc[ratio.index >= SHIFT_DAY]
    settled = ((post - 1.0).abs() <= tol)[::-1].cummin()[::-1]
    hits = settled[settled].index
    final = float(ratio.iloc[-smooth:].mean())
    return (float(hits[0] - SHIFT_DAY), final) if len(hits) else (np.nan, final)


def threshold_volatility(g):
    """Mean over participants of the SD of day-to-day changes in the end-of-day threshold, days 7+."""
    last = (g[g["user_threshold"].notna() & (g["day"] >= cc.RUN_IN_DAYS)]
            .sort_values("timestamp").groupby(["rep", "user_id", "day"])["user_threshold"].last())
    return float(last.groupby(level=[0, 1]).diff().groupby(level=[0, 1]).std().mean())


def run_robustness():
    t0 = time.time()
    oracle = build_oracle_map()
    oracle.to_csv(os.path.join(OUT, "robustness_oracle_map.csv"), index=False)
    n = DAYS * cc.EMA_PER_DAY
    outs = []
    for rep in range(N_REPS):
        rand_rng = np.random.default_rng([SEED, rep, 555])
        for scen in SCENARIOS:
            path_rng = np.random.default_rng([SEED, rep, 3])
            paths = [cc.scale_path(scen, n, SHIFT_DAY * cc.EMA_PER_DAY, path_rng) for _ in range(USERS)]
            cohort = cc.make_cohort(USERS, DAYS, SEED + rep, night=NIGHT, scale_paths=paths)
            frame = cc.engine_input(cohort, PROD["signal"], PROD["bridge"])
            for arm in ARMS:
                d = run_arm(frame, arm)
                d["delivered"] = d["send_prompt"].to_numpy() & (rand_rng.random(len(d)) < RANDOMIZATION_P)
                d["m_t"] = d["true_mssd"] * d["scale_t"] ** 2
                d["oracle_threshold"] = np.interp(d["m_t"], oracle["m"], oracle["threshold"])
                d["tracking_ratio"] = d["user_threshold"] / d["oracle_threshold"]
                outs.append(d.assign(scenario=scen, arm=arm, rep=rep))
    df = pd.concat(outs, ignore_index=True)
    outside = ((df["m_t"] < oracle["m"].min()) | (df["m_t"] > oracle["m"].max())) & df["evaluable"]
    save_json("robustness_oracle_coverage.json", {"m_min": oracle["m"].min(), "m_max": oracle["m"].max(),
              "share_evaluable_outside": float(outside.sum() / df["evaluable"].sum()),
              "by_scenario": outside.groupby(df["scenario"]).sum().div(df["evaluable"].groupby(df["scenario"]).sum()).to_dict()})
    print(f"robustness simulated in {time.time() - t0:.0f}s, {len(df):,} rows")

    full = pd.MultiIndex.from_product([range(N_REPS), [f"u{i:03d}" for i in range(USERS)], range(DAYS)],
                                      names=["rep", "user_id", "day"])
    day_rows = []
    for (scen, arm), g in df.groupby(["scenario", "arm"]):
        per = g.groupby(["rep", "user_id", "day"])[["send_prompt", "delivered"]].sum().reindex(full, fill_value=0)
        dose = per.groupby(level="day").agg(["mean", lambda x: 1.96 * x.std(ddof=1) / np.sqrt(x.size)])
        ev = g[g["evaluable"]]
        thr = ev.groupby("day").agg(tracking_ratio_med=("tracking_ratio", "median"),
                                    threshold_med=("user_threshold", "median"),
                                    oracle_med=("oracle_threshold", "median"), cross_rate=("crossed", "mean"))
        dd = pd.DataFrame({"eligible_mean": dose[("send_prompt", "mean")],
                           "delivered_mean": dose[("delivered", "mean")],
                           "delivered_ci": dose[("delivered", "<lambda_0>")]}).join(thr)
        day_rows.append(dd.reset_index().assign(scenario=scen, arm=arm))
    day_df = pd.concat(day_rows, ignore_index=True)
    day_df.to_csv(os.path.join(OUT, "robustness_by_day.csv"), index=False)

    rows = []
    for (scen, arm), g in df.groupby(["scenario", "arm"]):
        pre, post = g[g["day"] < SHIFT_DAY], g[g["day"] >= SHIFT_DAY]

        def ppw(x, n_days):
            per = x.groupby(["rep", "user_id"])["send_prompt"].sum().reindex(
                pd.MultiIndex.from_product([range(N_REPS), [f"u{i:03d}" for i in range(USERS)]]), fill_value=0)
            return float((per / (n_days / 7.0)).mean())

        readapt, final = days_to_readapt(day_df, scen, arm)
        ev, ev_pre, ev_post = g[g["evaluable"]], pre[pre["evaluable"]], post[post["evaluable"]]
        rows.append(dict(scenario=scen, arm=arm, **detection(g),
                         prompts_per_week_pre=ppw(pre, SHIFT_DAY), prompts_per_week_post=ppw(post, DAYS - SHIFT_DAY),
                         tracking_ratio_pre=float(ev_pre["tracking_ratio"].median()),
                         tracking_ratio_post=float(ev_post["tracking_ratio"].median()),
                         tracking_ratio_final=final, days_to_readapt=readapt,
                         crossing_rate=float(ev["crossed"].mean()), tie_rate=float(ev["tied"].mean()),
                         crossing_rate_last_week=float(ev[ev["day"] >= DAYS - 7]["crossed"].mean()),
                         threshold_volatility=threshold_volatility(g),
                         delivered_per_day_post=float(post.groupby(["rep", "user_id", "day"])["delivered"].sum().mean()),
                         n_evaluable=int(len(ev))))
    summ = pd.DataFrame(rows)
    summ.to_csv(os.path.join(OUT, "robustness_summary.csv"), index=False)
    pd.set_option("display.width", 250)
    print(summ.round(3).to_string(index=False))

    colors = {"stationary": "#52514e", "shift_up": "#eb6834", "shift_down": "#2a78d6", "drift": "#1baf7a"}
    labels = {"stationary": "stationary (control)", "shift_up": "shift up (σ ×2)",
              "shift_down": "shift down (σ ×0.5)", "drift": "drifting σ"}
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6), sharey=True)
    for ax, arm, title in zip(axes, ARMS, ("A. Production engine (expanding threshold)", "B. Rolling 7-day threshold")):
        for scen in SCENARIOS:
            s = day_df[(day_df["scenario"] == scen) & (day_df["arm"] == arm)].sort_values("day")
            ax.plot(s["day"], s["delivered_mean"], color=colors[scen], ls="--" if scen == "stationary" else "-",
                    label=labels[scen])
            ax.fill_between(s["day"], s["delivered_mean"] - s["delivered_ci"], s["delivered_mean"] + s["delivered_ci"],
                            color=colors[scen], alpha=0.15, lw=0)
        ax.axvspan(0, 7, color="#c9c8c3", alpha=0.3, lw=0); ax.axvline(SHIFT_DAY, color="0.4", ls=":", lw=1.2)
        ax.set_xlabel("study day"); ax.set_title(title); ax.grid(True, ls="--", alpha=0.4)
    axes[0].set_ylabel("delivered prompts per participant per day"); axes[0].legend(loc="upper left", fontsize=8)
    fig.suptitle("Intervention dosage over the study, production composite, after randomization (p = 0.50)", y=1.02)
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "dosage_over_time.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    xs, w = np.arange(len(SCENARIOS)), 0.36
    arm_color = {"expanding": "#4a3aa7", "rolling": "#e34948"}
    for ax, col, title in zip(axes, ("tpr", "fpr", "precision"),
                              ("Sensitivity (TPR)", "False-positive rate", "Precision")):
        top = 0
        for i, arm in enumerate(ARMS):
            vals = [float(summ[(summ.scenario == s) & (summ.arm == arm)][col].iloc[0]) for s in SCENARIOS]
            top = max(top, max(vals))
            ax.bar(xs + (i - 0.5) * w, vals, width=w - 0.03, color=arm_color[arm],
                   label="expanding (production)" if arm == "expanding" else "rolling 7-day")
            for x, v in zip(xs + (i - 0.5) * w, vals):
                ax.annotate(f"{v:.2f}", xy=(x, v), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=7.5)
        ref = float(summ[(summ.scenario == "stationary") & (summ.arm == "expanding")][col].iloc[0])
        ax.axhline(ref, color="0.35", ls="--", lw=1.2)
        ax.set_xticks(xs); ax.set_xticklabels([labels[s].replace(" (", "\n(") for s in SCENARIOS], fontsize=8)
        ax.set_title(title); ax.set_ylim(0, top * 1.3)
    axes[0].set_ylabel("rate"); axes[0].legend(loc="upper left", fontsize=8)
    fig.suptitle("Detection under non-stationary volatility, production composite", y=1.02)
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "detection_performance.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)


SECTIONS = {"calibration": run_calibration, "recovery": run_recovery, "sweep": run_sweep,
            "grid": run_grid, "robustness": run_robustness}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=sorted(SECTIONS))
    args = parser.parse_args()
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(FIG, exist_ok=True)
    for name, fn in SECTIONS.items():
        if args.only in (None, name):
            print(f"== {name}")
            fn()
