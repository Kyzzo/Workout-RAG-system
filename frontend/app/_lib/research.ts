// Explanations of the app's cited rules. The wording was tuned so no claim
// overstates its studies: rephrase lightly at most, never strengthen a claim,
// drop a caveat, or move a finding to a population the study didn't cover.
// Each item's rule keys supply its on-demand sources (GET /rules/{key}).

export type RuleExplanation = {
  title: string;
  text: string;
  keys: string[];
  // Heading for the second rule's sources, when there is one.
  secondHeading?: string;
};

export const HYPERTROPHY_RULES: RuleExplanation[] = [
  {
    title: "Volume",
    text: "Pelland et al. 2025's efficiency tiers: 5-10 weekly sets per muscle is the higher-efficiency tier, 11-18 the intermediate one.",
    keys: ["volume_efficiency_tiers"],
  },
  {
    title: "Frequency",
    text: "With weekly sets matched, studies show no significant growth difference between training a muscle 2x and 3x a week. More sessions still help at higher volumes, since gains within one session diminish past ~11 sets.",
    keys: ["frequency_matched_volume", "per_session_diminishing_returns"],
    secondHeading: "Why more sessions help at higher volume",
  },
];

const STRENGTH_COMMON: RuleExplanation[] = [
  {
    title: "Volume",
    text: "Pelland et al. 2025's strength efficiency tiers: 1 set is the minimum effective dose, 2 the higher-efficiency tier, 3-4 intermediate. More doesn't consistently add strength.",
    keys: ["strength_volume_efficiency_tiers"],
  },
  {
    title: "Loads",
    text: "Estimated from each exercise's reps and RIR using Nuzzo et al. 2024's table of reps to failure at each %1RM, so they fit together. People differ by about 2.5 reps at 80% 1RM, so treat the % as a starting weight and adjust it until sets end at the prescribed RIR.",
    keys: ["reps_at_percent_1rm"],
  },
  {
    title: "Frequency",
    text: "Strength gains rise with how often a lift is trained, with diminishing returns at higher frequencies.",
    keys: ["strength_frequency"],
  },
];

const STRENGTH_TRAINED: RuleExplanation[] = [
  {
    title: "Progression: daily undulating",
    text: "Each compound lift's sessions in the week rotate 8, 6 and 4 reps, heaviest last (Rhea et al. 2002's protocol), with each day's load set from its reps and RIR; the weight rises as you get stronger. Undulating periodization has produced larger 1RM gains than linear in trained lifters.",
    keys: ["periodization_by_training_status", "daily_undulating_protocol"],
    secondHeading: "The protocol the program follows",
  },
  {
    title: "Why daily, not weekly",
    text: "Undulating week to week hasn't beaten linear progression in trials.",
    keys: ["weekly_undulation_not_better"],
  },
  {
    title: "Session order",
    text: "The heaviest session comes last, not straight after the highest-volume one, and the exact rep numbers matter less than the volume. Rhea's 8/6/4 is one tested option.",
    keys: ["dup_session_order", "dup_rep_scheme"],
    secondHeading: "Why the exact reps matter less",
  },
];

const STRENGTH_UNTRAINED: RuleExplanation[] = [
  {
    title: "Progression: linear",
    text: "Compound lifts move through phases of 8, then 6, then 4 reps across the block (the linear arms of Rhea et al. 2002 and Buford et al. 2007), each week's load set from its reps and RIR. Undulating periodization's advantage over linear has been seen in trained lifters, not untrained.",
    keys: ["periodization_by_training_status", "linear_periodization_protocol"],
    secondHeading: "The protocol the program follows",
  },
];

const STRENGTH_TAIL: RuleExplanation[] = [
  {
    title: "Accessories",
    text: "Single-joint exercises stay at 8-12 reps every week, as in the strength trials, which periodized only the main lifts.",
    keys: ["strength_accessory_reps"],
  },
  {
    title: "Deload",
    text: "Off by default: in trained lifters, a week off partway through a 9-week program had minimal impact on muscle growth, and lower-body strength gains were modestly smaller than with continuous training. The deload's size here (60% of peak load) is common practice.",
    keys: ["deload_week"],
  },
];

export function rulesFor(goal: string, trained: boolean): RuleExplanation[] {
  if (goal !== "strength") return HYPERTROPHY_RULES;
  return [...STRENGTH_COMMON, ...(trained ? STRENGTH_TRAINED : STRENGTH_UNTRAINED), ...STRENGTH_TAIL];
}

// Shown in a hypertrophy block's weekly-sets analysis: frequency there isn't
// a generated number, so the cited finding stands in.
export const HYPERTROPHY_FREQUENCY: RuleExplanation = {
  title: "Frequency",
  text: "With weekly sets matched, studies show no significant growth difference between training a muscle 2x and 3x a week. More sessions help at higher volumes, since gains within one session diminish past ~11 sets.",
  keys: ["frequency_matched_volume", "per_session_diminishing_returns"],
  secondHeading: "Why more sessions help at higher volume",
};

// Double progression, for hypertrophy programs (the numbers don't schedule
// progression: the lifter does it session to session).
export const DOUBLE_PROGRESSION_STEPS: { lead: string; rest: string }[] = [
  { lead: "Start at the bottom.", rest: "Pick a weight that lets you hit the bottom of each exercise's rep range, around its prescribed effort (RIR)." },
  { lead: "Add reps.", rest: "Session to session, try to add reps at the same weight." },
  { lead: "Then add weight.", rest: "Once you reach the top of the range on every set, increase the weight by the smallest step available (often about 2.5-5%) and work back up from the bottom of the range." },
  { lead: "Keep form constant.", rest: "If reps only go up because your form breaks down, that isn't progress." },
  { lead: "Expect stalls.", rest: "Stalling for a few sessions is a normal part of progressing. Sleep, recovery and nutrition all play a role in how quickly your lifts move." },
];

export const DOUBLE_PROGRESSION_EVIDENCE: RuleExplanation = {
  title: "What the research shows",
  text: "Adding reps at the same weight built muscle as well as adding weight within a fixed rep range (trained lifters, 8 weeks). Combining the two - reps first, then weight at the top of the range (double progression) - and the 2.5-5% step are common practice, not tested as such.",
  keys: ["hypertrophy_rep_progression"],
};

export const SPLIT_RULE_KEY = "even_session_split";
export const SPLIT_RULE_HEADING = "Why the sets are spread evenly across sessions";
