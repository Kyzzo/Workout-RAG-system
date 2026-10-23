"use client";

import Link from "next/link";
import { useMemo, useRef, useState } from "react";
import { ChatPreview } from "../_chat/ChatSheet";
import { GeneratorForm } from "../_generator/GeneratorForm";
import { monthOf, shiftMonth, weekday, type ISODate } from "../_lib/tracker/dates";
import {
  blocksNeedingPlacement,
  buildSessions,
  focusSession,
  hasExercises,
  nextAfter,
  programEndDate,
  schedulable,
  sessionsByDate,
  summarize,
  type TrackerSummary,
} from "../_lib/tracker/schedule";
import type { Regimen, SessionLog } from "../_lib/tracker/types";
import { useApp } from "../_state/app";
import { useSession } from "../_state/session";
import { useTracker } from "../_state/tracker";
import { Icon } from "../_ui/Icon";
import { Masthead } from "../_ui/Masthead";
import { useToday } from "../_ui/useToday";
import { programTitle, type Program } from "../types";
import { Calendar } from "./Calendar";
import { RestSlab, SessionSlab } from "./SessionSlab";
import { DeviceNote, ScheduleSettings, StartTracking } from "./StartTracking";

export function WallPage() {
  const { status } = useSession();
  const app = useApp();
  const tracker = useTracker();
  const today = useToday();

  if (!today || status === "loading") return <WallLoading label="Lights coming on" />;
  if (status === "guest") return <GuestWall />;
  if (app.programs === null) {
    return app.listError ? (
      <WallProblem text={`Couldn’t load your programs: ${app.listError}`} onRetry={app.retryList} />
    ) : (
      <WallLoading label="Reading your programs" />
    );
  }
  if (app.programs.length === 0) return <FirstProgram />;
  if (!tracker.ready) return <WallLoading label="Reading the wall" />;
  if (tracker.loadError) return <WallProblem text={`Couldn’t read your tracking: ${tracker.loadError}`} />;

  const regimen = tracker.regimen;
  if (!regimen || tracker.programMissing || (tracker.intent !== null && tracker.intent !== regimen.programId)) {
    return (
      <div className="page wall">
        <Masthead title="Schedule" />
        <div className="wall-bare">
          <StartTracking today={today} />
        </div>
      </div>
    );
  }
  if (!tracker.program) {
    return tracker.programError ? (
      <WallProblem text={`Couldn’t load the program you’re tracking: ${tracker.programError}`} />
    ) : (
      <WallLoading label="Reading the program" />
    );
  }
  return <TrackedWall program={tracker.program} regimen={regimen} logs={tracker.logs} today={today} />;
}

function WallLoading({ label }: { label: string }) {
  return (
    <div className="page wall">
      <Masthead />
      <div className="wall-loading" role="status">
        <span className="tube" aria-hidden />
        <span className="label">{label}</span>
      </div>
    </div>
  );
}

function WallProblem({ text, onRetry }: { text: string; onRetry?: () => void }) {
  return (
    <div className="page wall">
      <Masthead />
      <div className="slab wall-problem" role="alert">
        <p className="error-text">{text}</p>
        {onRetry && (
          <button type="button" className="btn" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    </div>
  );
}

function Hero({ eyebrow }: { eyebrow: string }) {
  return (
    <section className="hero">
      <p className="label">{eyebrow}</p>
      <h1 className="hero-title painted">
        Nothing
        <br />
        scheduled.
      </h1>
      <p className="hero-lede">
        Build a training block and put it on the wall. Every set, rep, load and effort in it carries the studies behind
        it, each one checked before it’s shown.
      </p>
    </section>
  );
}

// A new user is led straight to building their first program.
function FirstProgram() {
  return (
    <div className="page wall first">
      <Masthead title="First program" />
      <div className="first-grid">
        <Hero eyebrow="An empty wall" />
        <section className="slab first-gen" aria-label="Build your first program">
          <GeneratorForm />
        </section>
      </div>
    </div>
  );
}

function GuestWall() {
  const { openSignIn } = useSession();
  return (
    <div className="page wall first">
      <Masthead title="Guest" />
      <div className="guest-banner" role="note">
        <span className="tag tag-hatch">Guest</span>
        <span>You’re looking around. Sign in to build programs, track sessions and ask the evidence desk.</span>
        <button type="button" className="btn btn-steel btn-small" onClick={openSignIn}>
          Sign in
        </button>
      </div>
      <div className="first-grid">
        <Hero eyebrow="Citeset" />
        <section className="slab first-gen" aria-label="Program generator">
          <GeneratorForm />
        </section>
      </div>
      <section className="slab guest-chat" aria-label="Evidence assistant">
        <ChatPreview />
      </section>
    </div>
  );
}

const pad2 = (n: number) => String(Math.max(0, n)).padStart(2, "0");

function WallHead({ summary, program }: { summary: TrackerSummary; program: Program }) {
  const { phase, currentWeek, totalWeeks, week, adherence, missed, streak, daysUntilStart } = summary;
  const pct = adherence.due ? Math.round((adherence.done / adherence.due) * 100) : null;
  return (
    <section className="wallhead" aria-label="Where you are">
      <div className="level" aria-label={phase === "before" ? `Starts in ${daysUntilStart} days` : `Week ${currentWeek} of ${totalWeeks}`}>
        <span className="label level-label">{phase === "before" ? "Starts in" : phase === "after" ? "Finished" : "Week"}</span>
        <span className="level-num painted" aria-hidden>
          {phase === "before" ? pad2(daysUntilStart) : pad2(currentWeek)}
        </span>
        <span className="level-of mono" aria-hidden>
          {phase === "before" ? (daysUntilStart === 1 ? "day" : "days") : `/${pad2(totalWeeks)}`}
        </span>
      </div>
      <dl className="stats">
        <div className="stat">
          <dt className="label">This week</dt>
          <dd>
            <span className="stat-num">{week.done}</span>
            <span className="stat-of">/{week.total} done</span>
          </dd>
        </div>
        <div className="stat">
          <dt className="label">Adherence</dt>
          <dd>
            <span className="stat-num">{pct === null ? "—" : `${pct}%`}</span>
            <span className="stat-of">
              {adherence.done}/{adherence.due} due
            </span>
          </dd>
        </div>
        <div className="stat">
          <dt className="label">Missed</dt>
          <dd>
            <span className="stat-num">{missed}</span>
          </dd>
        </div>
        <div className="stat">
          <dt className="label">Streak</dt>
          <dd>
            <span className="stat-num">{streak}</span>
            <span className="stat-of">in a row</span>
          </dd>
        </div>
      </dl>
      <p className="wallhead-line">
        <span className="serif-i">Tracking</span>{" "}
        <Link href="/program" className="link">
          {programTitle(program)}
        </Link>
      </p>
    </section>
  );
}

function TrackedWall({ program, regimen, logs, today }: { program: Program; regimen: Regimen; logs: Record<string, SessionLog>; today: ISODate }) {
  const sessions = useMemo(() => buildSessions(program, regimen, logs, today), [program, regimen, logs, today]);
  const byDate = useMemo(() => sessionsByDate(sessions), [sessions]);
  const summary = useMemo(() => summarize(sessions, program, regimen, today), [sessions, program, regimen, today]);
  const logList = useMemo(() => Object.values(logs), [logs]);
  const focus = focusSession(sessions, today);
  const [picked, setPicked] = useState<ISODate | null>(null);
  const [month, setMonth] = useState<{ year: number; month: number } | null>(null);
  const [settings, setSettings] = useState(false);
  const side = useRef<HTMLDivElement>(null);

  const selected = picked ?? focus?.date ?? today;
  const shown = month ?? monthOf(selected);
  const end = programEndDate(program, regimen.startDate) ?? regimen.startDate;
  const unplaced = blocksNeedingPlacement(program, regimen.dayOffsets);
  const daySessions = byDate.get(selected) ?? [];

  const bringIntoView = () => {
    const el = side.current;
    if (!el || window.matchMedia("(min-width: 960px)").matches) return;
    if (el.getBoundingClientRect().top > window.innerHeight * 0.66) {
      const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      el.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
    }
  };

  const select = (date: ISODate, follow: boolean) => {
    setPicked(date);
    if (follow) setMonth(monthOf(date));
    else requestAnimationFrame(bringIntoView);
  };

  const goToday = () => {
    const target = focusSession(sessions, today)?.date ?? today;
    setPicked(target);
    setMonth(monthOf(target));
  };

  return (
    <div className="page wall">
      <Masthead title="Schedule">
        <button
          type="button"
          className="btn btn-small"
          aria-expanded={settings}
          aria-controls="schedule-settings"
          onClick={() => setSettings((s) => !s)}
        >
          <Icon name="sliders" size={14} />
          <span className="hide-narrow">Schedule</span>
        </button>
      </Masthead>

      <WallHead summary={summary} program={program} />

      {unplaced.length > 0 && !settings && (
        <p className="caveat wall-caveat">
          <span className="caveat-mark">Check</span>
          <span>
            {unplaced.map((b) => b.name).join(", ")} {unplaced.length === 1 ? "has" : "have"} days without rest spacing,
            spread evenly for now.{" "}
            <button type="button" className="link" onClick={() => setSettings(true)}>
              Confirm or adjust them
            </button>
          </span>
        </p>
      )}
      {settings && <ScheduleSettings program={program} regimen={regimen} onClose={() => setSettings(false)} />}

      {!schedulable(program) || !hasExercises(program) ? (
        <div className="slab wall-problem">
          <p>
            Nothing to schedule yet: {programTitle(program)} has {schedulable(program) ? "no exercises" : "no days"} so far.{" "}
            <Link href="/program" className="link">
              Build it on the program page.
            </Link>
          </p>
        </div>
      ) : null}

      <div className="wall-grid">
        <div className="wall-cal">
          <Calendar
            year={shown.year}
            month={shown.month}
            firstWeekday={weekday(regimen.startDate)}
            byDate={byDate}
            today={today}
            selected={selected}
            rangeStart={regimen.startDate}
            rangeEnd={end}
            startDate={regimen.startDate}
            totalWeeks={summary.totalWeeks}
            onSelect={select}
            onMonth={(delta) => setMonth(shiftMonth(shown.year, shown.month, delta))}
            onToday={goToday}
          />
        </div>
        <div className="wall-side" ref={side}>
          {daySessions.length > 0 ? (
            <SessionSlab key={selected} sessions={daySessions} program={program} today={today} totalWeeks={summary.totalWeeks} logs={logList} />
          ) : (
            <RestSlab date={selected} today={today} next={nextAfter(sessions, selected)} onGo={(d) => select(d, true)} />
          )}
        </div>
      </div>
      <DeviceNote />
    </div>
  );
}
