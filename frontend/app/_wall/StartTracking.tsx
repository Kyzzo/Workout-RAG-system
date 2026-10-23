"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { addDays, isValidISO, longDate, type ISODate } from "../_lib/tracker/dates";
import { hasExercises, programEndWeek, schedulable } from "../_lib/tracker/schedule";
import { LocalTrackerStore, importLocalData, TRACKER_BACKEND } from "../_lib/tracker/store";
import type { Regimen } from "../_lib/tracker/types";
import { useProgramActions } from "../_state/actions";
import { useApp } from "../_state/app";
import { useDialogs } from "../_state/dialogs";
import { useSession } from "../_state/session";
import { useTracker } from "../_state/tracker";
import { Icon } from "../_ui/Icon";
import { programTitle, type Program } from "../types";
import { errorMessage } from "../useApi";
import { offsetsToStore, PlacementEditor } from "./Placement";

export function DeviceNote() {
  return TRACKER_BACKEND === "api" ? null : (
    <p className="device-note label">
      <span className="tiehole" aria-hidden /> Tracking is saved on this device only
    </p>
  );
}

function useTree(programId: number | null) {
  const { trees, treeErrors, loadTree } = useApp();
  useEffect(() => {
    if (programId === null || trees[programId] || treeErrors[programId]) return;
    void loadTree(programId);
  }, [programId, trees, treeErrors, loadTree]);
  return {
    tree: programId !== null ? (trees[programId] ?? null) : null,
    error: programId !== null ? (treeErrors[programId] ?? null) : null,
  };
}

// Choosing what goes on the wall: the program, the day week 1 begins, and
// where each training day sits in the week.
export function StartTracking({ today }: { today: ISODate }) {
  const app = useApp();
  const tracker = useTracker();
  const programs = app.programs ?? [];
  const current = tracker.regimen && !tracker.programMissing ? tracker.regimen : null;
  const [programId, setProgramId] = useState<number | null>(
    tracker.intent ?? app.selectedId ?? programs[0]?.id ?? null,
  );
  const [startDate, setStartDate] = useState<ISODate>(today);
  const [edits, setEdits] = useState<Record<number, number>>({});
  const [deleteOld, setDeleteOld] = useState(false);
  const [saving, setSaving] = useState(false);
  const { tree, error } = useTree(programId);
  const { titleOf } = useProgramActions();

  const switching = !!current && current.programId !== programId;
  const ready = !!tree && schedulable(tree) && isValidISO(startDate);

  const start = async () => {
    if (!tree || programId === null || !ready) return;
    setSaving(true);
    const ok = await tracker.startRegimen(
      { programId, startDate, dayOffsets: offsetsToStore(tree, edits) },
      { deleteLogsOf: switching && deleteOld && current ? current.programId : null },
    );
    setSaving(false);
    if (ok) tracker.setIntent(null);
  };

  return (
    <section className="slab setup" aria-labelledby="setup-title">
      <p className="label">{switching ? "Switch the wall" : "Nothing on the wall"}</p>
      <h2 id="setup-title" className="setup-title display">
        {switching ? "Track a different program" : "Put a program on the wall"}
      </h2>
      <p className="setup-lede">
        Pick the program you’re running and the day its first week begins. Its sessions land on the calendar, and you
        check them off as you train.
      </p>

      {tracker.programMissing && tracker.regimen && (
        <p className="caveat">
          <span className="caveat-mark">Gone</span>
          <span>The program you were tracking no longer exists. Choose another to put on the wall.</span>
        </p>
      )}

      <div className="setup-fields">
        <label className="field">
          <span className="field-label">Program</span>
          <select
            className="select"
            value={programId ?? ""}
            onChange={(e) => {
              setProgramId(Number(e.target.value));
              setEdits({});
            }}
          >
            {programs.map((p) => (
              <option key={p.id} value={p.id}>
                {programTitle(p)} ({p.goal})
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">Week 1 begins</span>
          <input type="date" className="input" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          <span className="field-hint">
            {isValidISO(startDate) ? `${longDate(startDate, true)}. Defaults to today.` : "Pick a date."}
          </span>
        </label>
      </div>

      {error && <p className="error-text">Couldn’t load this program: {error}</p>}
      {!tree && !error && programId !== null && <p className="label scanline loading-line">Reading the program</p>}
      {tree && !schedulable(tree) && (
        <p className="caveat">
          <span className="caveat-mark">Empty</span>
          <span>
            {programTitle(tree)} has no days to schedule yet. Add a block and its days on the{" "}
            <Link href="/program" className="link">
              program page
            </Link>{" "}
            first.
          </span>
        </p>
      )}
      {tree && schedulable(tree) && (
        <>
          {!hasExercises(tree) && (
            <p className="caveat">
              <span className="caveat-mark">Note</span>
              <span>Its days have no exercises yet, so sessions will be empty until you add some.</span>
            </p>
          )}
          <h3 className="setup-sub label">Where the sessions fall</h3>
          <PlacementEditor
            program={tree}
            startDate={isValidISO(startDate) ? startDate : today}
            offsets={edits}
            onChange={(dayId, o) => setEdits((e) => ({ ...e, [dayId]: o }))}
          />
          <p className="field-hint">
            {programEndWeek(tree)} weeks, ending{" "}
            {isValidISO(startDate) ? longDate(addDays(startDate, 7 * programEndWeek(tree) - 1), true) : "—"}.
          </p>
        </>
      )}

      {switching && current && (
        <label className="check setup-delete">
          <input type="checkbox" checked={deleteOld} onChange={(e) => setDeleteOld(e.target.checked)} />
          <span>
            Delete the tracking history of {titleOf(current.programId)}. Left unticked, it’s kept in case you go back to it.
          </span>
        </label>
      )}

      <div className="setup-actions">
        <button type="button" className="btn btn-steel" disabled={!ready || saving} onClick={start}>
          <Icon name="wall" size={15} /> {saving ? "Starting..." : switching ? "Switch and track" : "Start tracking"}
        </button>
        {switching && (
          <button type="button" className="btn btn-quiet" onClick={() => tracker.setIntent(null)}>
            Keep tracking {titleOf(current!.programId)}
          </button>
        )}
      </div>
      <DeviceNote />
    </section>
  );
}

// Adjusting the running schedule. Everything saves as it changes; logged
// sessions keep their dates.
export function ScheduleSettings({ program, regimen, onClose }: { program: Program; regimen: Regimen; onClose: () => void }) {
  const tracker = useTracker();
  const app = useApp();
  const { confirm } = useDialogs();
  const { userId, status } = useSession();
  const { titleOf } = useProgramActions();
  const [startDraft, setStartDraft] = useState(regimen.startDate);
  const others = (app.programs ?? []).filter((p) => p.id !== regimen.programId);
  const [switchTo, setSwitchTo] = useState<number | null>(others[0]?.id ?? null);
  const [importState, setImportState] = useState<string | null>(null);
  const localCount = status === "user" && userId && TRACKER_BACKEND === "api" ? new LocalTrackerStore(userId).snapshot().logs.length : 0;

  const stop = async (deleteLogs: boolean) => {
    const ok = await confirm({
      title: deleteLogs ? `Stop tracking and delete its history?` : `Stop tracking ${titleOf(regimen.programId)}?`,
      destructive: deleteLogs,
      consequences: deleteLogs
        ? ["The wall is cleared and every logged session of this program is deleted. This can't be undone."]
        : ["The wall is cleared. Logged sessions are kept, in case you track this program again."],
      confirmLabel: deleteLogs ? "Stop and delete" : "Stop tracking",
    });
    if (ok && (await tracker.stopRegimen(deleteLogs))) onClose();
  };

  return (
    <section className="slab settings" aria-labelledby="settings-title" id="schedule-settings">
      <div className="settings-head">
        <h2 id="settings-title" className="display settings-title">
          Schedule
        </h2>
        <button type="button" className="btn btn-quiet btn-icon" aria-label="Close schedule settings" onClick={onClose}>
          <Icon name="close" />
        </button>
      </div>
      <p className="field-hint">Changes move the sessions you haven’t logged. Logged sessions keep their dates.</p>

      <label className="field">
        <span className="field-label">Week 1 began</span>
        <input
          type="date"
          className="input"
          value={startDraft}
          onChange={(e) => {
            setStartDraft(e.target.value);
            if (isValidISO(e.target.value)) void tracker.updateRegimen({ startDate: e.target.value });
          }}
        />
      </label>

      <PlacementEditor
        program={program}
        startDate={regimen.startDate}
        offsets={regimen.dayOffsets}
        onChange={(dayId, o) => void tracker.updateRegimen({ dayOffsets: offsetsToStore(program, { ...regimen.dayOffsets, [dayId]: o }) })}
      />

      {others.length > 0 && (
        <div className="settings-row">
          <label className="field">
            <span className="field-label">Track another program</span>
            <select className="select" value={switchTo ?? ""} onChange={(e) => setSwitchTo(Number(e.target.value))}>
              {others.map((p) => (
                <option key={p.id} value={p.id}>
                  {programTitle(p)} ({p.goal})
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="btn" disabled={switchTo === null} onClick={() => switchTo !== null && tracker.setIntent(switchTo)}>
            Switch...
          </button>
        </div>
      )}

      {localCount > 0 && (
        <div className="settings-row">
          <p className="field-hint">
            {localCount} session{localCount === 1 ? "" : "s"} logged on this device before tracking moved to your account.
          </p>
          <button
            type="button"
            className="btn"
            onClick={async () => {
              if (!tracker.store || !userId) return;
              setImportState("Importing...");
              try {
                const n = await importLocalData(userId, tracker.store);
                setImportState(`Imported ${n} session${n === 1 ? "" : "s"}. Reload to see them.`);
              } catch (err) {
                setImportState(`Import failed: ${errorMessage(err)}`);
              }
            }}
          >
            Import them
          </button>
          {importState && <p role="status">{importState}</p>}
        </div>
      )}

      <div className="settings-stop">
        <button type="button" className="btn" onClick={() => stop(false)}>
          Stop tracking
        </button>
        <button type="button" className="btn btn-danger" onClick={() => stop(true)}>
          Stop and delete history
        </button>
      </div>
      <DeviceNote />
    </section>
  );
}
