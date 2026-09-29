import type { Program, WeeklyPrescription } from "./types";

export default function ProgramTree({
  program,
  anchoredFieldId,
  onAskAbout,
}: {
  program: Program;
  anchoredFieldId: number | null;
  onAskAbout: (prescription: WeeklyPrescription, label: string) => void;
}) {
  return (
    <div className="flex flex-col gap-4 w-full text-sm">
      <p className="text-zinc-500">
        Program #{program.id} - goal: {program.goal}
      </p>
      {program.mesocycles.map((mesocycle) => (
        <div key={mesocycle.id} className="border rounded p-3">
          <p className="font-medium">
            {mesocycle.name} (weeks {mesocycle.start_week}-{mesocycle.end_week})
          </p>
          <div className="flex flex-col gap-3 mt-2">
            {mesocycle.day_templates.map((day) => (
              <div key={day.id} className="pl-3 border-l">
                <p className="font-medium text-zinc-700 dark:text-zinc-300">{day.name}</p>
                <div className="flex flex-col gap-2 mt-1">
                  {day.exercise_slots.map((slot) => (
                    <div key={slot.id} className="pl-3">
                      <p className="text-zinc-600 dark:text-zinc-400">
                        {slot.exercise_name} ({slot.muscle_group})
                      </p>
                      <ul className="flex flex-col gap-1 mt-1">
                        {slot.weekly_prescriptions.map((wp) => {
                          const label = `${slot.exercise_name}, week ${wp.week_number}`;
                          const isAnchored = anchoredFieldId === wp.id;
                          return (
                            <li
                              key={wp.id}
                              className={`flex items-center justify-between gap-2 pl-3 rounded px-2 py-1 ${
                                isAnchored ? "bg-indigo-100 dark:bg-indigo-950" : ""
                              }`}
                            >
                              <span>
                                week {wp.week_number}: {wp.sets} sets - {wp.reps} reps - {wp.load}
                                {wp.grounding_note && (
                                  <span className="text-amber-600 text-xs ml-2">
                                    ({wp.grounding_note})
                                  </span>
                                )}
                              </span>
                              <button
                                type="button"
                                onClick={() => onAskAbout(wp, label)}
                                className="text-xs underline text-indigo-600 dark:text-indigo-400 shrink-0"
                              >
                                {isAnchored ? "anchored" : "ask about this"}
                              </button>
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
