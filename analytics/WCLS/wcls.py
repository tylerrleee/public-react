import warnings
from dataclasses import dataclass, field

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy.stats as st
import statsmodels.api as sm
from statsmodels.genmod.cov_struct import Autoregressive, Exchangeable, Independence

import data_loader as dl

FULL_CONTROLS = ("prior_valence", "prior_stress", "hour_c", "day_c")
SMALL_SAMPLE_CONTROLS = ("prior_valence",)
MIN_PARTICIPANTS_FOR_FULL_CONTROLS = 12
MODERATOR_SETS = {
    "marginal": (),
    "hour of day": ("hour_c",),
    "study day": ("day_c",),
    "baseline MSSD": ("mssd_c",),
}
MARGINAL_ONLY = {"marginal": ()}
GEE_STRUCTURES = {
    "GEE independence": Independence,
    "GEE exchangeable": Exchangeable,
    "GEE AR(1)": lambda: Autoregressive(grid=True),
}
METHODS = ("WCLS", *GEE_STRUCTURES)
EATERS_SUFFIX = "_eaters"
LEVERAGE_ONE = "a participant has leverage 1, so the small-sample correction is undefined"


class ModelNotEstimable(ValueError):
    pass


@dataclass(frozen=True)
class ModelSpec:
    outcome: str
    controls: tuple = FULL_CONTROLS
    moderators: tuple = ()
    label: str = "marginal"
    cluster: str = "user_id"

    @property
    def y_column(self):
        return dl.y_col(self.outcome)

    @property
    def g_columns(self):
        return list(dict.fromkeys([*self.controls, *self.moderators]))

    @property
    def term_names(self):
        return ["A", *(f"A × {m}" for m in self.moderators)]

    @property
    def required_columns(self):
        return list(dict.fromkeys([self.y_column, "A", "p", self.cluster, "anchor", *self.g_columns]))


@dataclass
class FitResult:
    method: str
    spec: ModelSpec
    beta: np.ndarray
    se: np.ndarray
    df: int
    n_participants: int
    n_points: int
    note: str = ""
    extra: dict = field(default_factory=dict)

    @classmethod
    def not_estimable(cls, method, spec, rows, reason):
        blank = np.full(len(spec.term_names), np.nan)
        return cls(method, spec, blank, blank, df=0, n_participants=rows[spec.cluster].nunique(),
                   n_points=len(rows), note=reason)

    def table(self, level=0.95):
        is_estimable = self.df > 0
        critical = st.t.ppf(0.5 + level / 2, self.df) if is_estimable else np.nan
        t_stat = self.beta / self.se
        return pd.DataFrame({
            "outcome": self.spec.outcome, "role": outcome_role(self.spec.outcome), "model": self.spec.label,
            "method": self.method, "term": self.spec.term_names, "estimate": self.beta, "se": self.se,
            "df": self.df, "p_value": 2 * st.t.sf(np.abs(t_stat), self.df) if is_estimable else np.nan,
            "ci_low": self.beta - critical * self.se, "ci_high": self.beta + critical * self.se,
            "n_participants": self.n_participants, "n_points": self.n_points, "note": self.note,
        })


def outcome_role(outcome):
    if outcome.endswith(EATERS_SUFFIX):
        return "sensitivity (eaters only)"
    return dl.OUTCOMES[outcome].role


def outcomes_with_role(*roles):
    return [name for name, spec in dl.OUTCOMES.items() if spec.role in roles]


def eaters_only_outcomes():
    return [f"{name}{EATERS_SUFFIX}" for name, spec in dl.OUTCOMES.items() if spec.kind == "eating_rating"]


def primary_sample(dp):
    return dp[dp["available"] & dp["in_analysis"]]


def complete_cases(sample, spec):
    return sample.dropna(subset=spec.required_columns).sort_values([spec.cluster, "anchor"]).reset_index(drop=True)


def participants_with_outcome(sample, outcome):
    return int(sample.loc[sample[dl.y_col(outcome)].notna(), "user_id"].nunique())


def choose_controls(n_participants):
    return FULL_CONTROLS if n_participants >= MIN_PARTICIPANTS_FOR_FULL_CONTROLS else SMALL_SAMPLE_CONTROLS


def default_spec(sample, outcome, moderators=(), label="marginal"):
    controls = choose_controls(participants_with_outcome(sample, outcome))
    return ModelSpec(outcome, controls, tuple(moderators), label)


def centering_probability(rows):
    return float(rows["p"].mean())


def wcls_weights(A, p, p_tilde):
    return np.where(A == 1, p_tilde / p, (1 - p_tilde) / (1 - p))


def _float_columns(rows, names):
    return [rows[name].to_numpy(float) for name in names]


def control_matrix(rows, spec):
    return np.column_stack([np.ones(len(rows)), *_float_columns(rows, spec.g_columns)])


def effect_matrix(rows, spec):
    return np.column_stack([np.ones(len(rows)), *_float_columns(rows, spec.moderators)])


def wcls_design(rows, spec, p_tilde):
    controls = control_matrix(rows, spec)
    centered_treatment = rows["A"].to_numpy(float) - p_tilde
    return np.hstack([controls, centered_treatment[:, None] * effect_matrix(rows, spec)]), controls.shape[1]


def gee_design(rows, spec):
    treatment = rows["A"].to_numpy(float)
    interactions = [treatment * moderator for moderator in _float_columns(rows, spec.moderators)]
    return np.column_stack([control_matrix(rows, spec), treatment, *interactions])


def require_estimable(X, y):
    if X.shape[0] < X.shape[1]:
        raise ModelNotEstimable(f"{X.shape[0]} rows for {X.shape[1]} parameters")
    if np.linalg.matrix_rank(X) < X.shape[1]:
        raise ModelNotEstimable("design matrix is rank-deficient")
    if np.unique(y).size < 2:
        raise ModelNotEstimable(f"outcome does not vary (every value is {y[0]:g})")


def participant_blocks(groups):
    starts = np.flatnonzero(np.r_[True, groups[1:] != groups[:-1], True])
    return list(zip(starts[:-1], starts[1:]))


def mancl_derouen_residuals(X_i, w_i, r_i, bread):
    leverage = (X_i @ bread @ X_i.T) * w_i[None, :]
    try:
        return np.linalg.solve(np.eye(len(r_i)) - leverage, r_i)
    except np.linalg.LinAlgError as error:
        raise ModelNotEstimable(LEVERAGE_ONE) from error


def sandwich_meat(X, w, residuals, blocks, bread, small_sample=True):
    meat = np.zeros_like(bread)
    for start, stop in blocks:
        X_i, w_i, r_i = X[start:stop], w[start:stop], residuals[start:stop]
        if small_sample:
            r_i = mancl_derouen_residuals(X_i, w_i, r_i, bread)
        score = X_i.T @ (w_i * r_i)
        meat += np.outer(score, score)
    return meat


def fit_wcls(sample, spec, small_sample=True):
    rows = complete_cases(sample, spec)
    p_tilde = centering_probability(rows)
    weights = wcls_weights(rows["A"].to_numpy(float), rows["p"].to_numpy(float), p_tilde)
    X, n_controls = wcls_design(rows, spec, p_tilde)
    y = rows[spec.y_column].to_numpy(float)
    require_estimable(X, y)
    bread = np.linalg.inv(X.T @ (weights[:, None] * X))
    theta = bread @ (X.T @ (weights * y))
    blocks = participant_blocks(rows[spec.cluster].to_numpy())
    covariance = bread @ sandwich_meat(X, weights, y - X @ theta, blocks, bread, small_sample) @ bread
    return FitResult("WCLS", spec, theta[n_controls:], np.sqrt(np.diag(covariance)[n_controls:]),
                     df=len(blocks) - X.shape[1], n_participants=len(blocks), n_points=len(rows),
                     extra=dict(p_tilde=p_tilde))


def first_dependence_parameter(dep_params):
    values = np.ravel(np.asarray(dep_params if dep_params is not None else [], dtype=float))
    return float(values[0]) if values.size else 0.0


def estimate_gee(model):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            fit = model.fit(cov_type="bias_reduced", maxiter=100)
            params, se = np.asarray(fit.params), np.asarray(fit.bse)
        except np.linalg.LinAlgError as error:
            raise ModelNotEstimable(LEVERAGE_ONE) from error
    return params, se, "; ".join(sorted({str(w.message) for w in caught}))


def fit_gee(sample, spec, structure="GEE exchangeable"):
    rows = complete_cases(sample, spec)
    X, y = gee_design(rows, spec), rows[spec.y_column].to_numpy(float)
    require_estimable(X, y)
    model = sm.GEE(y, X, groups=rows[spec.cluster].to_numpy(), time=rows.groupby(spec.cluster).cumcount().to_numpy(),
                   cov_struct=GEE_STRUCTURES[structure]())
    params, se, warning_text = estimate_gee(model)
    n_controls = X.shape[1] - len(spec.term_names)
    n_participants = rows[spec.cluster].nunique()
    return FitResult(structure, spec, params[n_controls:], se[n_controls:], df=n_participants - X.shape[1],
                     n_participants=n_participants, n_points=len(rows), note=warning_text,
                     extra=dict(working_correlation=first_dependence_parameter(model.cov_struct.dep_params)))


def fit_model(method, sample, spec):
    try:
        return fit_wcls(sample, spec) if method == "WCLS" else fit_gee(sample, spec, structure=method)
    except ModelNotEstimable as reason:
        return FitResult.not_estimable(method, spec, complete_cases(sample, spec), str(reason))


def run_outcome(sample, outcome, model_sets=MODERATOR_SETS, methods=METHODS):
    specs = [default_spec(sample, outcome, moderators, label) for label, moderators in model_sets.items()]
    return pd.concat([fit_model(method, sample, spec).table() for spec in specs for method in methods],
                     ignore_index=True)


def run_outcomes(sample, outcomes, model_sets=MODERATOR_SETS, methods=METHODS):
    return pd.concat([run_outcome(sample, outcome, model_sets, methods) for outcome in outcomes], ignore_index=True)


def centering_check(sample, hour_bands=(8, 11, 14, 17, 20, 23)):
    p_tilde = centering_probability(sample)
    weights = wcls_weights(sample["A"].to_numpy(float), sample["p"].to_numpy(float), p_tilde)
    banded = sample.assign(centered=weights * (sample["A"] - p_tilde), hour_band=pd.cut(sample["hour"], hour_bands))
    by_band = banded.groupby("hour_band", observed=True)
    return pd.DataFrame({
        "mean(A): uncentered": by_band["A"].mean(),
        "mean(W·(A − p̃)): WCLS treatment": by_band["centered"].mean(),
        "rows": by_band.size(),
    })


def side_by_side(results, methods=METHODS):
    cells = results["estimate"].map("{:+.3f}".format) + " ± " + results["se"].map("{:.3f}".format)
    wide = results.assign(cell=cells).pivot_table(index=["outcome", "model", "term"], columns="method",
                                                  values="cell", aggfunc="first")
    return wide[[method for method in methods if method in wide.columns]]


def working_correlations(sample, outcomes, structures=("GEE exchangeable", "GEE AR(1)")):
    records = [dict(outcome=outcome, structure=structure,
                    working_correlation=fit_model(structure, sample, default_spec(sample, outcome))
                    .extra.get("working_correlation", np.nan))
               for outcome in outcomes for structure in structures]
    return pd.DataFrame(records).pivot(index="outcome", columns="structure", values="working_correlation")


def forest_plot(results, methods=METHODS):
    labels = (results["outcome"] + " | " + results["model"] + " | " + results["term"]).tolist()
    order = list(dict.fromkeys(labels))
    offsets = dict(zip(methods, np.linspace(-0.27, 0.27, len(methods))))
    fig, ax = plt.subplots(figsize=(9, 0.42 * len(order) + 1.2))
    for method, group in results.assign(label=labels).groupby("method", sort=False):
        positions = [order.index(label) + offsets[method] for label in group["label"]]
        error = [group["estimate"] - group["ci_low"], group["ci_high"] - group["estimate"]]
        ax.errorbar(group["estimate"], positions, xerr=error, fmt="o", capsize=2, label=method)
    ax.axvline(0, color="grey", linewidth=0.8)
    ax.set_yticks(range(len(order)), order)
    ax.invert_yaxis()
    ax.set_xlabel("Effect of sending a prompt, on the outcome's scale (95% CI)")
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    return ax


def statsmodels_check(sample, spec):
    rows = complete_cases(sample, spec)
    p_tilde = centering_probability(rows)
    X, n_controls = wcls_design(rows, spec, p_tilde)
    weights = wcls_weights(rows["A"].to_numpy(float), rows["p"].to_numpy(float), p_tilde)
    reference = sm.WLS(rows[spec.y_column].to_numpy(float), X, weights=weights).fit(
        cov_type="cluster", cov_kwds={"groups": rows[spec.cluster].to_numpy()})
    corrected, uncorrected = fit_wcls(sample, spec), fit_wcls(sample, spec, small_sample=False)
    reference_beta = np.asarray(reference.params[n_controls:])
    return pd.DataFrame({
        "outcome": spec.outcome, "model": spec.label, "term": spec.term_names,
        "beta (WCLS)": corrected.beta, "beta (statsmodels WLS)": reference_beta,
        "agrees to 1e-10": np.isclose(corrected.beta, reference_beta, rtol=0, atol=1e-10),
        "se Mancl-DeRouen": corrected.se, "se uncorrected": uncorrected.se,
        "se CR1 (statsmodels)": np.asarray(reference.bse[n_controls:]),
    })


def true_effect(sample, truth, spec):
    rows = complete_cases(sample, spec).merge(truth, on="jitai_log_id", how="left")
    return float(rows[f"true_{spec.outcome}"].mean())


def truth_recovery(sample, truth, outcomes, methods=METHODS):
    records = []
    for outcome in outcomes:
        spec = default_spec(sample, outcome)
        target = true_effect(sample, truth, spec)
        for method in methods:
            fit = fit_model(method, sample, spec).table().iloc[0]
            records.append(dict(outcome=outcome, method=method, estimate=fit["estimate"], ci_low=fit["ci_low"],
                                ci_high=fit["ci_high"], truth=target,
                                truth_in_ci=bool(fit["ci_low"] <= target <= fit["ci_high"])))
    return pd.DataFrame(records).set_index(["outcome", "method"])
