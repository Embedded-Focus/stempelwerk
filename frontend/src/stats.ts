export type GroupBy = "file" | "top-level" | "heading";

export interface StatsEntry {
  start: Date;
  end: Date;
  fileId: string;
  headingId: string;
  /** The heading title. */
  title: string;
  /** Top-level first; the last element is the heading itself. */
  outline: string[];
}

export interface GroupTotal {
  key: string;
  /** Main text of the row. */
  label: string;
  /** Muted text after the label, or null. */
  detail: string | null;
  /** Set only for the "file" grouping; used for the swatch. */
  fileId: string | null;
  minutes: number;
}

export interface DayTotal {
  /** Local midnight at the start of the day. */
  date: Date;
  minutes: number;
}

export interface Stats {
  totalMinutes: number;
  entryCount: number;
  groups: GroupTotal[];
  days: DayTotal[];
}

const MAX_GROUPS = 8;

function overlapMs(start: Date, end: Date, from: Date, to: Date): number {
  const begin = Math.max(start.getTime(), from.getTime());
  const finish = Math.min(end.getTime(), to.getTime());
  return Math.max(0, finish - begin);
}

export function computeStats(
  entries: StatsEntry[],
  rangeStart: Date,
  rangeEnd: Date,
  groupBy: GroupBy
): Stats {
  const kept = entries.filter(
    (entry) => overlapMs(entry.start, entry.end, rangeStart, rangeEnd) > 0
  );
  const totalMs = kept.reduce(
    (sum, entry) => sum + overlapMs(entry.start, entry.end, rangeStart, rangeEnd),
    0
  );
  const totalMinutes = Math.round(totalMs / 60000);

  const groupMs = new Map<
    string,
    { label: string; detail: string | null; fileId: string | null; ms: number }
  >();
  for (const entry of kept) {
    let key: string;
    let label: string;
    let detail: string | null;
    let fileId: string | null = null;
    if (groupBy === "file") {
      key = entry.fileId;
      label = entry.fileId;
      detail = null;
      fileId = entry.fileId;
    } else if (groupBy === "top-level") {
      const topLevel = entry.outline.length > 0 ? entry.outline[0] : entry.title;
      key = `${entry.fileId}\u0000${topLevel}`;
      label = topLevel;
      detail = entry.fileId;
    } else {
      const parentPath = entry.outline.slice(0, -1).join(" / ");
      key = entry.headingId;
      label = entry.title;
      detail = parentPath !== "" ? parentPath : entry.fileId;
    }

    const existing = groupMs.get(key);
    const ms = overlapMs(entry.start, entry.end, rangeStart, rangeEnd);
    if (existing === undefined) {
      groupMs.set(key, { label, detail, fileId, ms });
    } else {
      existing.ms += ms;
    }
  }

  const sorted = [...groupMs.entries()]
    .map(([key, value]) => ({ key, ...value, minutes: Math.round(value.ms / 60000) }))
    .sort((a, b) => b.minutes - a.minutes || a.label.localeCompare(b.label));

  let groups: GroupTotal[] = sorted;
  if (sorted.length > MAX_GROUPS) {
    const head = sorted.slice(0, MAX_GROUPS - 1);
    const rest = sorted.slice(MAX_GROUPS - 1);
    const restMinutes = rest.reduce((sum, group) => sum + group.minutes, 0);
    groups = [
      ...head,
      {
        key: "__other__",
        label: `Other (${rest.length} groups)`,
        detail: null,
        fileId: null,
        minutes: restMinutes
      }
    ];
  }

  const days: DayTotal[] = [];
  const cursor = new Date(
    rangeStart.getFullYear(),
    rangeStart.getMonth(),
    rangeStart.getDate()
  );
  let index = 0;
  while (cursor.getTime() < rangeEnd.getTime()) {
    const dayStart = new Date(cursor);
    const nextDayStart = new Date(
      rangeStart.getFullYear(),
      rangeStart.getMonth(),
      rangeStart.getDate() + index + 1
    );
    const dayMs = kept.reduce(
      (sum, entry) => sum + overlapMs(entry.start, entry.end, dayStart, nextDayStart),
      0
    );
    days.push({ date: dayStart, minutes: Math.round(dayMs / 60000) });
    cursor.setDate(cursor.getDate() + 1);
    index += 1;
  }

  return { totalMinutes, entryCount: kept.length, groups, days };
}

export function formatMinutes(totalMinutes: number): string {
  return `${Math.floor(totalMinutes / 60)}:${String(totalMinutes % 60).padStart(2, "0")}`;
}
