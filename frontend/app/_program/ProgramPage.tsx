"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { GeneratorForm } from "../_generator/GeneratorForm";
import { sortedBlocks } from "../_lib/format";
import { longDate } from "../_lib/tracker/dates";
import { schedulable } from "../_lib/tracker/schedule";
import { useProgramActions } from "../_state/actions";
import { useApp } from "../_state/app";
import { useSession } from "../_state/session";
import { useTracker } from "../_state/tracker";
import { useUi } from "../_state/ui";
import { Icon } from "../_ui/Icon";
import { Masthead } from "../_ui/Masthead";
import { Menu } from "../_ui/Menu";
import { programLabel, programTitle, shortVolumeLabel, volumeLabel, type Program, type ProgramSummary } from "../types";
import { BlockSection } from "./BlockSection";
import { AddBlockForm } from "./Forms";
import { ProgressionGuide } from "./ProgressionGuide";

export function ProgramPage() {
  const { status, openSignIn } = useSession();
  const app = useApp();

  if (status === "loading") return <Quiet label="Lights coming on" />;
  if (status === "guest") {
    return (
      <div className="page doss">
        <Masthead title="Program" />
        <div className="slab doss-empty">
          <p className="label">Guest</p>
          <h1 className="display doss-empty-title">Your programs live here.</h1>
          <p>Sign in to build one: every block, day and exercise, each number with the studies behind it.</p>
          <button type="button" className="btn btn-steel" onClick={openSignIn}>
            Sign in
          </button>
        </div>
      </div>
    );
  }
  if (app.programs === null) {
    return app.listError ? (
      <div className="page doss">
        <Masthead title="Program" />
        <div className="slab doss-empty" role="alert">
          <p className="error-text">Couldn’t load your programs: {app.listError}</p>
          <button type="button" className="btn" onClick={app.retryList}>
            Try again
          </button>
        </div>
      </div>
    ) : (
      <Quiet label="Reading your programs" />
    );
  }
  if (app.programs.length === 0) {
    return (
      <div className="page doss">
        <Masthead title="Program" />
        <section className="slab doss-first" aria-label="Build your first program">
          <p className="label">No programs yet</p>
          <h1 className="display doss-empty-title">Build your first program</h1>
          <GeneratorForm />
        </section>
      </div>
    );
  }
  return <Dossier />;
}

function Quiet({ label }: { label: string }) {
  return (
    <div className="page doss">
      <Masthead title="Program" />
      <div className="wall-loading" role="status">
        <span className="tube" aria-hidden />
        <span className="label">{label}</span>
      </div>
    </div>
  );
}

function Dossier() {
  const app = useApp();
  const tracker = useTracker();
  const { select, remove } = useProgramActions();
  const { openNew } = useUi();
  const router = useRouter();
  const summary = app.programs?.find((p) => p.id === app.selectedId) ?? null;
  const program = app.program;
  const generatingHere = !!app.run && !app.run.result && app.run.programId === app.selectedId;

  return (
    <div className="page doss">
      <Masthead title="Program">
        <button type="button" className="btn btn-small" onClick={openNew} disabled={!!app.run && !app.run.result}>
          <Icon name="plus" size={14} />
          <span className="hide-narrow">New program</span>
        </button>
      </Masthead>

      <header className="doss-head">
        <label className="doss-switch">
          <span className="label">Program</span>
          <select className="select" value={app.selectedId ?? ""} onChange={(e) => select(Number(e.target.value))}>
            {(app.programs ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {programLabel(p)}
              </option>
            ))}
          </select>
        </label>

        {summary && (
          <>
            {/* Long split names ("Push/Pull/Legs") may break after a slash, never mid-word. */}
            <h1 className="doss-title painted">{programTitle(summary).replace(/\//g, "/\u200B")}</h1>
            <Meta summary={summary} program={program} />
            <div className="doss-actions">
              <TrackingControl program={program} onTrack={(id) => {
                tracker.setIntent(id);
                router.push("/");
              }} />
              <Menu
                label="Program options"
                text="Options"
                className="btn btn-small"
                disabled={app.locked}
                items={[
                  { label: "Rename program", icon: "edit", onSelect: () => void app.renameProgram(summary.id) },
                  "sep",
                  { label: "Delete program", icon: "trash", danger: true, onSelect: () => void remove(summary.id) },
                ]}
              />
            </div>
            {generatingHere && (
              <p className="caveat doss-generating" role="status">
                <span className="caveat-mark scanline">Live</span>
                <span>This program is generating. Its values fill in below as each step finishes; its actions wait until it’s done.</span>
              </p>
            )}
          </>
        )}
      </header>

      {app.programError ? (
        <div className="slab doss-empty" role="alert">
          <p className="error-text">Couldn’t load this program: {app.programError}</p>
          <button type="button" className="btn" onClick={() => app.selectedId !== null && void app.refreshTree(app.selectedId)}>
            Try again
          </button>
        </div>
      ) : !program ? (
        <div className="wall-loading" role="status">
          <span className="tube" aria-hidden />
          <span className="label">Reading the program</span>
        </div>
      ) : (
        <ProgramBody key={program.id} program={program} />
      )}
    </div>
  );
}

function Meta({ summary, program }: { summary: ProgramSummary; program: Program | null }) {
  const goal = program?.goal ?? summary.goal;
  const volume = program?.volume_preference ?? summary.volume_preference ?? "moderate";
  const trained = program?.trained ?? summary.trained ?? false;
  const deload = program?.include_deload ?? summary.include_deload ?? false;
  return (
    <p className="doss-meta">
      <span className="tag tag-solid">{goal}</span>
      <span className="doss-volume">
        <span className="hide-narrow">{volumeLabel(volume, goal)}</span>
        <span className="show-narrow">{shortVolumeLabel(volume, goal)}</span>
      </span>
      {goal === "strength" && (
        <>
          <span className="tag">{trained ? "Lifting 1+ year" : "Under a year"}</span>
          <span className="tag">{deload ? "Deload week included" : "No deload week"}</span>
        </>
      )}
    </p>
  );
}

function TrackingControl({ program, onTrack }: { program: Program | null; onTrack: (id: number) => void }) {
  const tracker = useTracker();
  if (!program) return null;
  const tracked = tracker.regimen?.programId === program.id && !tracker.programMissing;
  if (tracked && tracker.regimen) {
    return (
      <Link href="/" className="btn btn-small doss-tracked">
        <Icon name="wall" size={14} />
        On the wall since {longDate(tracker.regimen.startDate)}
      </Link>
    );
  }
  const ready = schedulable(program);
  return (
    <button
      type="button"
      className="btn btn-steel btn-small"
      disabled={!ready}
      title={ready ? undefined : "Add a block with at least one day first"}
      onClick={() => onTrack(program.id)}
    >
      <Icon name="wall" size={14} />
      Start tracking this program
    </button>
  );
}

function ProgramBody({ program }: { program: Program }) {
  const blocks = sortedBlocks(program);
  return (
    <div className="doss-body">
      {program.goal !== "strength" && blocks.length > 0 && <ProgressionGuide />}
      {blocks.length === 0 ? (
        <section className="slab doss-empty">
          <p className="label">No blocks yet</p>
          <h2 className="display doss-empty-title">Start with a block</h2>
          <p>
            A block is a run of weeks that repeat the same training days. Add one, then its days, then the exercises on
            each day. Generate the numbers once the exercises are in.
          </p>
          <AddBlockForm program={program} startOpen />
        </section>
      ) : (
        <>
          {blocks.map((block, i) => (
            <BlockSection key={block.id} block={block} program={program} index={i} />
          ))}
          <AddBlockForm program={program} />
        </>
      )}
    </div>
  );
}
