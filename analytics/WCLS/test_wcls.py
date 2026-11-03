import unittest
import warnings

import numpy as np
import pandas as pd

import data_loader as dl
import wcls

OUTCOME = "B7_urge"
TRUE_BETA = -0.5


def make_sample(n_users=40, per_user=30, seed=7, p_by_hour=None, evening_shift=0.0):
    rng = np.random.default_rng(seed)
    n = n_users * per_user
    hour_c = rng.uniform(-6, 6, n)
    p = np.full(n, 0.5) if p_by_hour is None else np.where(hour_c > 0, p_by_hour[1], p_by_hour[0])
    A = (rng.random(n) < p).astype(float)
    person = np.repeat(rng.normal(0, 0.5, n_users), per_user)
    prior_valence = rng.integers(1, 8, n).astype(float)
    y = 3 + person + 0.3 * prior_valence + evening_shift * (hour_c > 0) + TRUE_BETA * A + rng.normal(0, 1, n)
    return pd.DataFrame({
        "user_id": np.repeat(np.arange(n_users), per_user), "jitai_log_id": np.arange(n),
        "anchor": pd.Timestamp("2026-11-01", tz="UTC") + pd.to_timedelta(np.tile(np.arange(per_user), n_users), "h"),
        "available": True, "in_analysis": True, "p": p, "A": A, "hour": hour_c + 15, "hour_c": hour_c,
        "prior_valence": prior_valence, "prior_stress": rng.integers(1, 8, n).astype(float),
        "day_c": rng.uniform(-14, 14, n), "mssd_c": rng.normal(0, 1, n), dl.y_col(OUTCOME): y,
    })


def fit_marginal(method, sample, controls=wcls.FULL_CONTROLS):
    return wcls.fit_model(method, sample, wcls.ModelSpec(OUTCOME, controls))


class WeightTests(unittest.TestCase):
    def test_weights_reshape_to_the_centering_probability(self):
        weights = wcls.wcls_weights(np.array([1.0, 0.0]), np.array([0.25, 0.25]), 0.5)
        np.testing.assert_allclose(weights, [2.0, 2 / 3])

    def test_constant_probability_gives_unit_weights(self):
        weights = wcls.wcls_weights(np.array([1.0, 0.0, 1.0]), np.full(3, 0.5), 0.5)
        np.testing.assert_allclose(weights, 1.0)


class EstimatorTests(unittest.TestCase):
    def test_point_estimates_match_statsmodels_wls(self):
        sample = make_sample()
        for moderators in ((), ("hour_c",)):
            check = wcls.statsmodels_check(sample, wcls.ModelSpec(OUTCOME, wcls.FULL_CONTROLS, moderators))
            self.assertTrue(check["agrees to 1e-10"].all())

    def test_gee_independence_equals_wcls_when_p_is_constant(self):
        sample = make_sample()
        for moderators in ((), ("hour_c",)):
            spec = wcls.ModelSpec(OUTCOME, wcls.FULL_CONTROLS, moderators)
            wcls_fit = wcls.fit_model("WCLS", sample, spec)
            gee_fit = wcls.fit_model("GEE independence", sample, spec)
            np.testing.assert_allclose(gee_fit.beta, wcls_fit.beta, atol=1e-8)
            np.testing.assert_allclose(gee_fit.se, wcls_fit.se, rtol=1e-6)

    def test_wcls_is_unbiased_when_p_depends_on_an_uncontrolled_history(self):
        sample = make_sample(n_users=60, per_user=40, p_by_hour=(0.3, 0.7), evening_shift=1.0)
        wcls_fit = fit_marginal("WCLS", sample, controls=("prior_valence",))
        gee_fit = fit_marginal("GEE independence", sample, controls=("prior_valence",))
        self.assertLess(abs(wcls_fit.beta[0] - TRUE_BETA), 3 * wcls_fit.se[0])
        self.assertGreater(abs(gee_fit.beta[0] - TRUE_BETA), 3 * gee_fit.se[0])

    def test_small_sample_correction_widens_the_standard_error(self):
        sample = make_sample(n_users=8)
        spec = wcls.ModelSpec(OUTCOME, wcls.SMALL_SAMPLE_CONTROLS)
        corrected = wcls.fit_wcls(sample, spec)
        uncorrected = wcls.fit_wcls(sample, spec, small_sample=False)
        self.assertTrue((corrected.se > uncorrected.se).all())


class InferenceTests(unittest.TestCase):
    def test_df_is_participants_minus_parameters(self):
        fit = fit_marginal("WCLS", make_sample(n_users=8), controls=wcls.SMALL_SAMPLE_CONTROLS)
        self.assertEqual(fit.df, 8 - 2 - 1)
        self.assertTrue(fit.table()[["ci_low", "ci_high", "p_value"]].notna().all().all())

    def test_no_df_left_gives_no_interval(self):
        table = fit_marginal("WCLS", make_sample(n_users=5)).table()
        self.assertEqual(table["df"].iloc[0], 5 - 5 - 1)
        self.assertTrue(table[["ci_low", "ci_high", "p_value"]].isna().all().all())

    def test_controls_drop_to_prior_valence_below_twelve_participants(self):
        self.assertEqual(wcls.choose_controls(11), wcls.SMALL_SAMPLE_CONTROLS)
        self.assertEqual(wcls.choose_controls(12), wcls.FULL_CONTROLS)


class SpecificationTests(unittest.TestCase):
    def test_every_moderator_is_also_a_control(self):
        spec = wcls.ModelSpec(OUTCOME, ("prior_valence", "hour_c"), ("hour_c", "mssd_c"))
        self.assertEqual(spec.g_columns, ["prior_valence", "hour_c", "mssd_c"])
        self.assertEqual(spec.term_names, ["A", "A × hour_c", "A × mssd_c"])

    def test_primary_sample_keeps_available_in_analysis_rows_only(self):
        sample = make_sample(n_users=2, per_user=3)
        sample.loc[0, "available"] = False
        sample.loc[1, "in_analysis"] = False
        self.assertEqual(len(wcls.primary_sample(sample)), 4)

    def test_eaters_only_outcomes_follow_the_registry(self):
        self.assertEqual(wcls.eaters_only_outcomes(),
                         ["B4_emotion_influence_eaters", "B4_loss_of_control_eaters"])
        self.assertEqual(wcls.outcome_role("B4_emotion_influence_eaters"), "sensitivity (eaters only)")


class NotEstimableTests(unittest.TestCase):
    def test_constant_outcome_is_reported_not_raised(self):
        sample = make_sample(n_users=6)
        sample[dl.y_col(OUTCOME)] = 1.0
        for method in wcls.METHODS:
            fit = fit_marginal(method, sample, controls=wcls.SMALL_SAMPLE_CONTROLS)
            self.assertIn("does not vary", fit.note)
            self.assertTrue(np.isnan(fit.beta).all())

    def test_too_few_rows_is_reported_not_raised(self):
        fit = fit_marginal("WCLS", make_sample(n_users=1, per_user=3))
        self.assertIn("rows for", fit.note)


class SyntheticRecoveryTests(unittest.TestCase):
    def test_wcls_recovers_the_primary_effects(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            frames = dl.load_frames("synthetic", n_users=30, seed=2026)
            sample = wcls.primary_sample(dl.build_analysis_table(frames))
        recovery = wcls.truth_recovery(sample, frames.truth, dl.PRIMARY_OUTCOMES, methods=("WCLS",))
        self.assertTrue(recovery["truth_in_ci"].all(), recovery)


if __name__ == "__main__":
    unittest.main()
