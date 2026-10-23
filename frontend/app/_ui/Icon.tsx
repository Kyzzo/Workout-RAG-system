// Hand-drawn stroke icons: square caps, mitred joins, no rounding. Always
// decorative (aria-hidden) - the control carries the accessible name.

const PATHS: Record<string, string> = {
  wall: "M3 4h18v16H3zM3 9h18M3 14.5h18M8 4v5M14 9v5.5M9 14.5V20M17.5 4v5",
  plan: "M4 3h11l5 5v13H4zM15 3v5h5M7.5 12.5h9M7.5 16.5h6",
  ask: "M4 4h16v12H11l-5 4v-4H4zM8 9h8M8 12.5h5",
  plus: "M12 4v16M4 12h16",
  close: "M5 5l14 14M19 5L5 19",
  check: "M4.5 12.5l4.5 4.5 10.5-11",
  left: "M15 4l-8 8 8 8",
  right: "M9 4l8 8-8 8",
  down: "M4 9l8 8 8-8",
  up: "M4 15l8-8 8 8",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  warning: "M12 3l10 18H2zM12 9.5v5M12 17.5v.5",
  note: "M12 4v16M5.1 8l13.8 8M18.9 8L5.1 16",
  source: "M5 4h10l4 4v12H5zM8.5 11h7M8.5 14.5h7M8.5 18h4",
  stop: "M6 6h12v12H6z",
  undo: "M9 6L4 11l5 5M4 11h10a6 6 0 010 12h-2",
  swap: "M4 8h14l-4-4M20 16H6l4 4",
  trash: "M4 6.5h16M9 6.5V4h6v2.5M6.5 6.5L7.5 20h9l1-13.5M10 10.5v6M14 10.5v6",
  edit: "M4 20h4L19.5 8.5l-4-4L4 16zM13.5 6.5l4 4",
  spark: "M12 3v5M12 16v5M3 12h5M16 12h5M6 6l3 3M15 15l3 3M18 6l-3 3M9 15l-3 3",
  moved: "M4 16a8 8 0 0114.5-4.5M19.5 6.5v5h-5",
  today: "M12 4v2M12 18v2M4 12h2M18 12h2M12 9a3 3 0 100 6 3 3 0 000-6z",
  sliders: "M4 7h10M18 7h2M4 17h4M12 17h8M14 5v4M8 15v4",
  send: "M4 12h14M13 6l6 6-6 6",
  user: "M12 4a4 4 0 100 8 4 4 0 000-8zM4.5 20.5c1-4 4-6 7.5-6s6.5 2 7.5 6",
  bolt: "M13 3L5 13.5h6L10 21l8-10.5h-6z",
  flag: "M5 21V4M5 4h12l-2.5 4L17 12H5",
  layers: "M12 4l9 4.5-9 4.5-9-4.5zM3 13l9 4.5 9-4.5",
  dot: "M12 10.5v3",
  skip: "M5 5l14 14M5 12a7 7 0 1014 0 7 7 0 00-14 0",
  key: "M14.5 9.5a4 4 0 11-8 0 4 4 0 018 0zM13.5 12l7 7M17.5 16l2-2",
};

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 18, className }: { name: IconName | string; size?: number; className?: string }) {
  const d = PATHS[name] ?? PATHS.dot;
  return (
    <svg
      className={className ? `icon ${className}` : "icon"}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={name === "more" ? 3 : 1.6}
      strokeLinecap="square"
      strokeLinejoin="miter"
      aria-hidden
      focusable="false"
    >
      <path d={d} />
    </svg>
  );
}
