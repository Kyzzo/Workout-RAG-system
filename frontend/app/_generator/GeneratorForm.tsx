"use client";

import { useId, useState } from "react";
import { rulesFor } from "../_lib/research";
import { RuleSources } from "../_sources/RuleSources";
import { GUEST_SPLITS, useApp } from "../_state/app";
import { useSession } from "../_state/session";
import { Icon } from "../_ui/Icon";
import { VOLUME_BANDS, VOLUME_LABELS, type Goal, type SplitOut, type VolumePreference } from "../types";

const VOLUMES: VolumePreference[] = ["minimal", "moderate", "high"];

function perMuscle(days: number, split: SplitOut) {
  const per = days / split.day_types.length;
  return Number.isInteger(per) ? `${per}` : per.toFixed(1);
}

// The allowed day count whose per-muscle frequency is closest to `target`.
function closestDays(split: SplitOut, target: number): number {
  return [...split.allowed_days].sort(
    (a, b) => Math.abs(a / split.day_types.length - target) - Math.abs(b / split.day_types.length - target) || a - b,
  )[0];
}

function band(goal: Goal, pref: VolumePreference) {
  const [lo, hi] = VOLUME_BANDS[goal][pref];
  return lo === hi ? `${lo}` : `${lo}-${hi}`;
}

export function GeneratorForm() {
  const { status } = useSession();
  const app = useApp();
  const ids = useId();
  const signedIn = status === "user";
  const splits = signedIn ? app.splits : GUEST_SPLITS;

  const [goal, setGoal] = useState<Goal>("hypertrophy");
  const [splitKey, setSplitKey] = useState<string | null>(null);
  const [days, setDays] = useState<number | null>(null);
  const [volume, setVolume] = useState<VolumePreference>("moderate");
  const [weeks, setWeeks] = useState(6);
  const [trained, setTrained] = useState(false);
  const [deload, setDeload] = useState(false);
  const [rulesOpen, setRulesOpen] = useState(false);

  const split = splits?.find((s) => s.key === splitKey) ?? splits?.[0] ?? null;
  const chosenDays = split ? (days !== null && split.allowed_days.includes(days) ? days : closestDays(split, 2)) : null;
  const generating = !!app.run && !app.run.result;
  // Guests see the form as it is; the guest gate turns any touch into sign-in.
  const disabled = generating;
  const strength = goal === "strength";
  const rules = rulesFor(goal, trained);

  const changeSplit = (key: string) => {
    const next = splits?.find((s) => s.key === key);
    if (!next) return;
    // Keep the per-muscle frequency as close as the new split allows.
    const current = split && chosenDays ? chosenDays / split.day_types.length : 2;
    setSplitKey(key);
    setDays(closestDays(next, current));
  };

  const generate = () => {
    if (!split || !chosenDays || disabled || !signedIn) return;
    void app.startGenerator({
      goal,
      split: split.key,
      days_per_week: chosenDays,
      weeks,
      volume_preference: volume,
      trained: strength && trained,
      include_deload: strength && deload,
    });
  };

  return (
    <form
      className="gen"
      onSubmit={(e) => {
        e.preventDefault();
        generate();
      }}
    >
      <fieldset className="gen-fields" disabled={disabled}>
        <legend className="sr-only">Program choices</legend>

        <div className="gen-row">
          <span className="field-label" id={`${ids}-goal`}>
            Goal
          </span>
          <div className="seg" role="radiogroup" aria-labelledby={`${ids}-goal`}>
            {(["hypertrophy", "strength"] as Goal[]).map((g) => (
              <button key={g} type="button" role="radio" aria-checked={goal === g} onClick={() => setGoal(g)}>
                {g === "hypertrophy" ? "Hypertrophy" : "Strength"}
              </button>
            ))}
          </div>
        </div>

        <label className="field">
          <span className="field-label">Split</span>
          {splits ? (
            <select className="select" value={split?.key ?? ""} onChange={(e) => changeSplit(e.target.value)}>
              {splits.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          ) : app.splitsError ? (
            <span className="error-text">Couldn’t load the splits: {app.splitsError}</span>
          ) : (
            <span className="label scanline loading-line">Loading splits</span>
          )}
          {split && (
            <span className="gen-rotation">
              <span className="label">Rotates</span>
              {split.day_types.map((t, i) => (
                <span key={t} className="gen-daytype">
                  {i > 0 && <span aria-hidden className="gen-arrow">→</span>}
                  {t}
                </span>
              ))}
            </span>
          )}
        </label>

        {split && chosenDays !== null && (
          <label className="field">
            <span className="field-label">Frequency</span>
            <select className="select" value={chosenDays} onChange={(e) => setDays(Number(e.target.value))}>
              {split.allowed_days.map((d) => (
                <option key={d} value={d}>
                  {perMuscle(d, split)}x per muscle · {d} days/week
                </option>
              ))}
            </select>
          </label>
        )}

        <div className="field" role="radiogroup" aria-labelledby={`${ids}-vol`}>
          <span className="field-label" id={`${ids}-vol`}>
            Weekly volume
          </span>
          <div className="gen-volumes">
            {VOLUMES.map((v) => (
              <button
                key={v}
                type="button"
                role="radio"
                aria-checked={volume === v}
                className="gen-volume"
                onClick={() => setVolume(v)}
              >
                <span className="gen-volume-name">{VOLUME_LABELS[v]}</span>
                <span className="gen-volume-band">
                  <span className="gen-volume-num">{band(goal, v)}</span> sets/week per muscle
                </span>
              </button>
            ))}
          </div>
          <span className="field-hint">
            Sets per muscle each week. Secondary work, where a muscle assists in another muscle’s exercise, counts as half a set.
          </span>
        </div>

        <div className="field">
          <span className="field-label" id={`${ids}-len`}>
            Length
          </span>
          <div className="stepper" role="group" aria-labelledby={`${ids}-len`}>
            <button type="button" className="btn btn-icon" aria-label="One week fewer" disabled={weeks <= 2} onClick={() => setWeeks((w) => Math.max(2, w - 1))}>
              <Icon name="left" size={16} />
            </button>
            <output className="stepper-value" aria-live="polite">
              <span className="stepper-num">{weeks}</span> weeks
            </output>
            <button type="button" className="btn btn-icon" aria-label="One week more" disabled={weeks >= 12} onClick={() => setWeeks((w) => Math.min(12, w + 1))}>
              <Icon name="right" size={16} />
            </button>
          </div>
        </div>

        {strength && (
          <div className="gen-strength">
            <label className="check">
              <input type="checkbox" checked={trained} onChange={(e) => setTrained(e.target.checked)} />
              <span>
                <span className="gen-check-title">I’ve lifted consistently for 1+ year</span>
                <span className="field-hint">
                  {trained
                    ? "Daily undulating progression: 8, 6 and 4 reps across the week."
                    : "Linear progression: phases of 8, then 6, then 4 reps."}
                </span>
              </span>
            </label>
            <label className="check">
              <input type="checkbox" checked={deload} onChange={(e) => setDeload(e.target.checked)} />
              <span>
                <span className="gen-check-title">Include a deload week</span>
                <span className="field-hint">A lighter final week in each block. Off by default, for the reason under Deload below.</span>
              </span>
            </label>
          </div>
        )}
      </fieldset>

      <div className="gen-rules">
        <button
          type="button"
          className="gen-rules-toggle"
          aria-expanded={rulesOpen}
          aria-controls={`${ids}-rules`}
          onClick={() => setRulesOpen((o) => !o)}
        >
          <span className="display">How this program is built</span>
          <span className="tag">{rules.length} cited rules</span>
          <Icon name={rulesOpen ? "up" : "down"} size={14} />
        </button>
        {rulesOpen && (
          <div id={`${ids}-rules`} className="gen-rules-list">
            {rules.map((rule) => (
              <RuleSources key={rule.title} rule={rule} />
            ))}
          </div>
        )}
      </div>

      <div className="gen-actions">
        <button type="submit" className="btn btn-steel gen-go" disabled={disabled || !split || !chosenDays}>
          <Icon name="bolt" size={16} />
          {generating ? "Generating..." : "Generate program"}
        </button>
        <button
          type="button"
          className="btn btn-quiet"
          disabled={disabled || app.locked}
          onClick={() =>
            void app.createEmpty({ goal, volume_preference: volume, trained: strength && trained, include_deload: strength && deload })
          }
        >
          Start empty instead
        </button>
      </div>
      <p className="field-hint gen-foot">
        Generating chooses exercises for each day, then fills in every number with verified citations. It takes a few
        minutes; you can watch it fill in.
      </p>
    </form>
  );
}
