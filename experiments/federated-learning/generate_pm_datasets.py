#!/usr/bin/env python3
"""Generate synthetic predictive-maintenance CSVs for Module G FL lab.

Realistic demo settings: class overlap, sensor noise, label noise, and a
held-out test set with slight distribution shift (accuracy typically 82-92%,
not 100%).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

FEATURES = [
    "vibration_rms",
    "vibration_peak",
    "temperature_c",
    "motor_current_a",
    "load_pct",
    "hours_since_service",
]

# overlap=0.55 -> failure centroids pulled toward healthy (harder separation)
REALISM = {
    "overlap": 0.55,
    "sigma_scale": 1.75,
    "label_noise": 0.08,
    "feature_jitter": 0.06,
    "test_shift": 0.12,
    "test_label_noise": 0.05,
}

PROFILES = {
    1: {
        "name": "CNC spindle (board-alpha)",
        "seed": 19,
        "n": 200,
        "healthy": dict(
            vibration_rms=(1.2, 0.25),
            vibration_peak=(2.5, 0.4),
            temperature_c=(45, 4),
            motor_current_a=(8.5, 0.8),
            load_pct=(55, 10),
            hours_since_service=(120, 40),
        ),
        "failure": dict(
            vibration_rms=(4.8, 0.6),
            vibration_peak=(9.5, 1.0),
            temperature_c=(62, 5),
            motor_current_a=(11.0, 1.0),
            load_pct=(78, 8),
            hours_since_service=(480, 60),
        ),
    },
    2: {
        "name": "Conveyor motor (board-beta)",
        "seed": 29,
        "n": 200,
        "healthy": dict(
            vibration_rms=(0.9, 0.2),
            vibration_peak=(1.8, 0.3),
            temperature_c=(38, 3),
            motor_current_a=(5.5, 0.5),
            load_pct=(40, 8),
            hours_since_service=(200, 50),
        ),
        "failure": dict(
            vibration_rms=(2.2, 0.4),
            vibration_peak=(4.5, 0.6),
            temperature_c=(78, 6),
            motor_current_a=(7.8, 0.7),
            load_pct=(65, 10),
            hours_since_service=(600, 80),
        ),
    },
    3: {
        "name": "Pump line (board-gamma)",
        "seed": 37,
        "n": 200,
        "healthy": dict(
            vibration_rms=(1.0, 0.18),
            vibration_peak=(2.0, 0.35),
            temperature_c=(42, 3.5),
            motor_current_a=(6.2, 0.6),
            load_pct=(50, 9),
            hours_since_service=(150, 45),
        ),
        "failure": dict(
            vibration_rms=(3.5, 0.5),
            vibration_peak=(7.0, 0.8),
            temperature_c=(58, 4),
            motor_current_a=(10.5, 0.9),
            load_pct=(82, 7),
            hours_since_service=(520, 70),
        ),
    },
}


def _blend_spec(healthy: dict, failure: dict, overlap: float) -> dict:
    """Move failure centroids toward healthy for harder classification."""
    out = {}
    for col in FEATURES:
        h_mu, h_sigma = healthy[col]
        f_mu, f_sigma = failure[col]
        out[col] = (
            f_mu * (1.0 - overlap) + h_mu * overlap,
            f_sigma * REALISM["sigma_scale"],
        )
    return out


def _sample(rng: np.random.Generator, spec: dict, n: int) -> pd.DataFrame:
    rows = {}
    for col in FEATURES:
        mu, sigma = spec[col]
        rows[col] = rng.normal(mu, sigma, n).clip(0.01, None)
    return pd.DataFrame(rows)


def _jitter_features(rng: np.random.Generator, df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in FEATURES:
        scale = out[col].std() * REALISM["feature_jitter"]
        if scale > 0:
            out[col] = (out[col] + rng.normal(0, scale, len(out))).clip(0.01, None)
    return out


def _flip_labels(rng: np.random.Generator, df: pd.DataFrame, rate: float) -> pd.DataFrame:
    out = df.copy()
    if rate <= 0 or len(out) == 0:
        return out
    mask = rng.random(len(out)) < rate
    out.loc[mask, "target"] = 1 - out.loc[mask, "target"]
    return out


def generate_machine(machine_id: int) -> pd.DataFrame:
    profile = PROFILES[machine_id]
    rng = np.random.default_rng(profile["seed"])
    n = profile["n"]
    n_fail = max(30, n // 4)
    n_ok = n - n_fail
    healthy_spec = profile["healthy"]
    failure_spec = _blend_spec(profile["healthy"], profile["failure"], REALISM["overlap"])
    healthy = _sample(rng, healthy_spec, n_ok)
    failing = _sample(rng, failure_spec, n_fail)
    df = pd.concat([healthy, failing], ignore_index=True)
    df["target"] = [0] * n_ok + [1] * n_fail
    df = df.sample(frac=1, random_state=profile["seed"]).reset_index(drop=True)
    df = _jitter_features(rng, df)
    df = _flip_labels(rng, df, REALISM["label_noise"])
    return df[FEATURES + ["target"]]


def generate_test(rng_seed: int = 99) -> pd.DataFrame:
    """Held-out mix with distribution shift vs edge training CSVs."""
    rng = np.random.default_rng(rng_seed)
    parts = []
    shift = REALISM["test_shift"]
    for mid in (1, 2, 3):
        profile = PROFILES[mid]
        n = 60
        n_fail = 15
        healthy_spec = profile["healthy"]
        failure_spec = _blend_spec(profile["healthy"], profile["failure"], REALISM["overlap"])
        # Slight covariate shift on test only
        healthy_shifted = {
            k: (v[0] * (1 + shift * (mid - 2) * 0.05), v[1] * REALISM["sigma_scale"])
            for k, v in healthy_spec.items()
        }
        failure_shifted = {
            k: (v[0] * (1 + shift * (mid - 2) * 0.03), v[1] * REALISM["sigma_scale"])
            for k, v in failure_spec.items()
        }
        healthy = _sample(rng, healthy_shifted, n - n_fail)
        failing = _sample(rng, failure_shifted, n_fail)
        part = pd.concat([healthy, failing], ignore_index=True)
        part["target"] = [0] * (n - n_fail) + [1] * n_fail
        parts.append(part)
    df = pd.concat(parts, ignore_index=True)
    df = df.sample(frac=1, random_state=rng_seed).reset_index(drop=True)
    df = _jitter_features(rng, df)
    df = _flip_labels(rng, df, REALISM["test_label_noise"])
    return df


def augment_heart_csv(path: Path, out_path: Path, seed: int) -> None:
    """Add noise to heart cohort CSVs so accuracy stays in a realistic band."""
    rng = np.random.default_rng(seed)
    df = pd.read_csv(path)
    numeric = [c for c in df.columns if c != "target"]
    for col in numeric:
        if pd.api.types.is_numeric_dtype(df[col]):
            noise = rng.normal(0, df[col].std() * 0.10, len(df))
            df[col] = df[col] + noise
    df = _flip_labels(rng, df, 0.06)
    df.to_csv(out_path, index=False)


def build_heart_test(out: Path) -> None:
    parts = []
    for mid in (1, 2, 3):
        path = out / f"heart_{mid}.csv"
        if path.is_file():
            df_h = pd.read_csv(path)
            parts.append(df_h.sample(n=min(20, len(df_h)), random_state=mid + 200))
    if parts:
        heart_test = pd.concat(parts, ignore_index=True)
        rng = np.random.default_rng(301)
        heart_test = _flip_labels(rng, heart_test, 0.05)
        heart_test.to_csv(out / "data_test_heart.csv", index=False)
        print(f"Wrote {out / 'data_test_heart.csv'} ({len(heart_test)} rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "vendor" / "ch19",
    )
    args = parser.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    for mid, profile in PROFILES.items():
        path = out / f"machine_{mid}.csv"
        df = generate_machine(mid)
        df.to_csv(path, index=False)
        fail_rate = df["target"].mean()
        print(
            f"Wrote {path} ({len(df)} rows, failure rate {fail_rate:.1%}) - {profile['name']}"
        )

    test_path = out / "data_test_pm.csv"
    test_df = generate_test()
    test_df.to_csv(test_path, index=False)
    print(f"Wrote {test_path} ({len(test_df)} rows, failure rate {test_df['target'].mean():.1%})")

    for mid in (1, 2, 3):
        src = out / f"heart_{mid}.csv"
        if src.is_file():
            augment_heart_csv(src, src, seed=100 + mid)

    build_heart_test(out)


if __name__ == "__main__":
    main()
