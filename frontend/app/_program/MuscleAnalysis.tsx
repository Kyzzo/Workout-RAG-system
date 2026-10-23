"use client";

import { useId, useState } from "react";
import { analyseBlock, rangeText, type MuscleRow } from "../_lib/analysis";
import { frequencySources, progressionSources, sourcesState, volumeSources, type SourcesRequest } from "../_lib/evidence";
import { capitalize, schemeLabel } from "../_lib/format";
import { HYPERTROPHY_FREQUENCY } from "../_lib/research";
import { RuleSources } from "../_sources/RuleSources";
import { useApp } from "../_state/app";
import { useSources } from "../_state/sources";
import { Icon } from "../_ui/Icon";
import { Menu } from "../_ui/Menu";
import type { Mesocycle, Program } from "../types";
import { useProgramOps } from "./useProgramOps";

// Weekly sets per muscle against the research target, one brick per set.
export function MuscleAnalysis({ block, program }: { block: Mesocycle; program: Program }) {
  const a = analyseBlock(block, program.goal);
  const strength = program.goal === "strength";
  const [details, setDetails] = useState(false);
  const id = useId();
  if (!a.rows.length) return null;

  const targetText = a.targetRange
    ? strength
      ? `${rangeText(a.targetRange)} ${a.targetRange[0] === a.targetRange[1] ? "is" : "are"} enough for strength`
      : `${rangeText(a.targetRange)} suggested`
    : "no targets generated yet";

  return (
    <section className="musc" aria-labelledby={`${id}-h`}>
      <header className="musc-head">
        <h3 id={`${id}-h`} className="label musc-title">
          Weekly sets by muscle
        </h3>
        <p className="musc-summary">
          <span>{targetText}</span>
          {a.daysRange && <span>trained {rangeText(a.daysRange)}x/wk</span>}
          {a.belowCount > 0 ? (
            <span className="tag tag-solid">
              <span aria-hidden>▼</span> {a.belowCount} below target
            </span>
          ) : (
            a.targetRange && <span className="tag">All at target</span>
          )}
        </p>
      </header>

      <ul className="musc-rows" style={{ "--max": a.maxScale } as React.CSSProperties}>
        {a.rows.map((row, i) => (
          <MuscleBar key={row.muscle} row={row} block={block} program={program} index={i} />
        ))}
      </ul>

      <button type="button" className="rule-toggle musc-toggle" aria-expanded={details} aria-controls={`${id}-d`} onClick={() => setDetails((d) => !d)}>
        <Icon name="layers" size={14} /> Dosing details <Icon name={details ? "up" : "down"} size={12} />
      </button>
      {details && <Details id={`${id}-d`} block={block} program={program} />}
    </section>
  );
}

function MuscleBar({ row, block, program, index }: { row: MuscleRow; block: Mesocycle; program: Program; index: number }) {
  const { locked, busy } = useApp();
  const ops = useProgramOps(program);
  const strength = program.goal === "strength";
  const working = busy?.scope === `muscle:${block.id}:${row.muscle}` ? busy.working : null;
  const span = Math.max(row.delivered, row.target ?? 0);
  const label = row.indirect
    ? `${capitalize(row.muscle)}: ${row.delivered} weekly sets, only as half sets from other lifts, no research target`
    : `${capitalize(row.muscle)}: ${row.delivered} weekly sets${row.target !== null ? ` against a target of ${row.target}${row.below ? ", below target" : ""}` : ", no target generated yet"}`;

  return (
    <li className="mrow" data-below={row.below || undefined} data-indirect={row.indirect || undefined} data-working={working ? "" : undefined} style={{ "--i": index } as React.CSSProperties}>
      <span className="mrow-name">
        {capitalize(row.muscle)}
        {row.indirect && <span className="mrow-sub">half sets only</span>}
      </span>
      <span className="bricks" role="img" aria-label={label}>
        {Array.from({ length: span }, (_, i) => (
          <span key={i} className="brick" data-on={i < row.delivered || undefined} data-over={row.target !== null && i >= row.target ? "" : undefined} />
        ))}
        {row.target !== null && <span className="bricks-target" style={{ "--t": row.target } as React.CSSProperties} />}
      </span>
      <span className="mrow-num mono">
        {row.delivered}
        {row.target !== null && <span className="quiet">/{row.target}</span>}
        {row.below && (
          <span className="mrow-below" title="Below target">
            <span aria-hidden>▼</span>
          </span>
        )}
      </span>
      <span className="mrow-tools">
        {working ? (
          <span className="tag scanline" role="status">
            {working}
          </span>
        ) : (
          !row.indirect && (
            <Menu
              label={`${capitalize(row.muscle)} options`}
              disabled={locked}
              items={[
                { label: "Generate weekly volume", icon: "bolt", onSelect: () => void ops.muscleVolume(block, row.muscle) },
                ...(strength
                  ? [
                      { label: "Generate frequency", icon: "spark" as const, onSelect: () => void ops.muscleFrequency(block, row.muscle) },
                      { label: "Generate progression", icon: "spark" as const, onSelect: () => void ops.muscleProgression(block, row.muscle) },
                    ]
                  : []),
                { note: strength ? "Frequency here may add days to reach it." : "Volume may add exercises to fit the sets." },
              ]}
            />
          )
        )}
      </span>
    </li>
  );
}

function SourcesLink({ request, text }: { request: SourcesRequest; text: string }) {
  const { openSources } = useSources();
  const state = sourcesState(request);
  if (state.kind === "none") return <span className="dose-value">{text}</span>;
  return (
    <button
      type="button"
      className="vchip"
      data-kind={state.kind}
      aria-label={
        state.kind === "cited"
          ? `${text}: show ${state.count} verified source${state.count === 1 ? "" : "s"}`
          : `${text}: no verified source - see the note`
      }
      onClick={() => openSources(request)}
    >
      <span className="vchip-text">{text}</span>
      {state.kind === "cited" ? <span className="vchip-count" aria-hidden>{state.count}</span> : <span className="vchip-note" aria-hidden>※</span>}
    </button>
  );
}

function Details({ id, block, program }: { id: string; block: Mesocycle; program: Program }) {
  const a = analyseBlock(block, program.goal);
  const strength = program.goal === "strength";
  const primary = a.rows.filter((r) => !r.indirect);
  const common = a.commonDays;

  return (
    <div id={id} className="dose">
      <dl className="dose-shared">
        {a.sharedVolume && (
          <div className="dose-item">
            <dt className="label">Weekly sets target</dt>
            <dd>
              <SourcesLink request={volumeSources(a.sharedVolume, program.goal)} text={`${a.sharedVolume.weekly_sets} per muscle`} />
            </dd>
          </div>
        )}
        {strength && a.sharedFrequency && (
          <div className="dose-item">
            <dt className="label">Research frequency</dt>
            <dd>
              <SourcesLink request={frequencySources(a.sharedFrequency, program.goal, "each muscle")} text={`${a.sharedFrequency.frequency}x/week`} />
            </dd>
          </div>
        )}
        {common && (
          <div className="dose-item">
            <dt className="label">Days trained</dt>
            <dd className="dose-value">
              {common.days}x/week
              {common.exceptions.length > 0 && (
                <span className="quiet"> · {common.exceptions.map((e) => `${e.muscle} ${e.days}x`).join(", ")}</span>
              )}
            </dd>
          </div>
        )}
      </dl>

      {!strength && (
        <div className="dose-finding">
          <p className="label">Frequency</p>
          <RuleSources rule={HYPERTROPHY_FREQUENCY} compact />
        </div>
      )}

      <ul className="dose-muscles">
        {primary.map((row) => {
          const parts: React.ReactNode[] = [];
          if (!common) parts.push(<span key="days">Trained {row.daysTraining}x/week</span>);
          if (strength && row.frequency && !a.sharedFrequency)
            parts.push(
              <span key="freq">
                Research: <SourcesLink request={frequencySources(row.frequency, program.goal, row.muscle)} text={`${row.frequency.frequency}x/week`} />
              </span>,
            );
          if (row.volume && !a.sharedVolume)
            parts.push(
              <span key="vol">
                Target: <SourcesLink request={volumeSources(row.volume, program.goal)} text={`${row.volume.weekly_sets} sets/week`} />
              </span>,
            );
          if (!strength && row.avgPerSession !== null) parts.push(<span key="avg">~{row.avgPerSession} sets on average per session</span>);
          if (strength && row.scheme)
            parts.push(
              <span key="prog">
                Progression: <SourcesLink request={progressionSources(row.scheme, program)} text={schemeLabel(row.scheme.scheme)} />
              </span>,
            );
          if (!parts.length) return null;
          return (
            <li key={row.muscle} className="dose-muscle">
              <span className="dose-muscle-name">{capitalize(row.muscle)}</span>
              <span className="dose-parts">{parts}</span>
            </li>
          );
        })}
      </ul>
      {a.rows.some((r) => r.indirect) && (
        <p className="field-hint">Muscles marked “half sets only” are trained only as the secondary muscle of other lifts, so they have no research target.</p>
      )}
    </div>
  );
}
