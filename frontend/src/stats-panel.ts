import { computeStats, formatMinutes, type GroupBy, type GroupTotal, type StatsEntry } from "./stats";

export type { StatsEntry } from "./stats";

export interface StatsPanelOptions {
  colorForFile: (fileId: string) => string;
}

export interface StatsPanelData {
  entries: StatsEntry[];
  rangeStart: Date;
  rangeEnd: Date;
  /** The calendar title, for example "Jul 27 – Aug 2, 2026". */
  rangeTitle: string;
  /** True for the week view; false for the day view. */
  isWeek: boolean;
}

export interface StatsPanel {
  element: HTMLElement;
  update: (data: StatsPanelData) => void;
}

const GROUP_BY_KEY = "stempelwerk.stats.groupBy";
const GROUP_BY_VALUES: GroupBy[] = ["file", "top-level", "heading"];

export function createStatsPanel(options: StatsPanelOptions): StatsPanel {
  let lastData: StatsPanelData | null = null;

  const groupBy = readGroupBy();

  const element = document.createElement("section");
  element.className = "stats-panel";
  element.setAttribute("aria-label", "Statistics");

  const header = document.createElement("header");
  header.className = "stats-header";
  const heading = document.createElement("h2");
  heading.className = "stats-heading";
  const groupLabel = document.createElement("label");
  groupLabel.className = "stats-group-label";
  const groupText = document.createElement("span");
  groupText.textContent = "Group by";
  const groupSelect = document.createElement("select");
  groupSelect.className = "stats-group-select";
  for (const [value, text] of [
    ["file", "File"],
    ["top-level", "Top-level heading"],
    ["heading", "Heading"]
  ] as const) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = text;
    groupSelect.append(option);
  }
  groupSelect.value = groupBy;
  groupSelect.addEventListener("change", () => {
    const next = groupSelect.value as GroupBy;
    window.localStorage.setItem(GROUP_BY_KEY, next);
    lastGroupBy = next;
    render();
  });
  groupLabel.append(groupText, groupSelect);
  header.append(heading, groupLabel);

  const tiles = document.createElement("div");
  tiles.className = "stats-tiles";

  const body = document.createElement("div");
  body.className = "stats-body";
  const breakdown = document.createElement("div");
  breakdown.className = "stats-breakdown";
  const breakdownHeading = document.createElement("h3");
  breakdownHeading.className = "stats-subheading";
  const rows = document.createElement("ol");
  rows.className = "stats-rows";
  breakdown.append(breakdownHeading, rows);
  const daysSection = document.createElement("div");
  daysSection.className = "stats-days";
  const daysHeading = document.createElement("h3");
  daysHeading.className = "stats-subheading";
  daysHeading.textContent = "By day";
  const columns = document.createElement("div");
  columns.className = "stats-columns";
  daysSection.append(daysHeading, columns);
  body.append(breakdown, daysSection);

  const note = document.createElement("p");
  note.className = "stats-note";
  note.textContent = "Overlapping entries count in full.";

  const empty = document.createElement("p");
  empty.className = "stats-empty";
  empty.textContent = "No entries in this range.";
  empty.hidden = true;

  element.append(header, tiles, body, note, empty);

  let lastGroupBy: GroupBy = groupBy;

  const update = (data: StatsPanelData): void => {
    lastData = data;
    render();
  };

  function render(): void {
    if (lastData === null) {
      return;
    }
    const { entries, rangeStart, rangeEnd, rangeTitle, isWeek } = lastData;
    const stats = computeStats(entries, rangeStart, rangeEnd, lastGroupBy);

    heading.textContent = `Summary · ${rangeTitle}`;
    breakdownHeading.textContent =
      lastGroupBy === "file"
        ? "By file"
        : lastGroupBy === "top-level"
          ? "By top-level heading"
          : "By heading";
    daysSection.hidden = !isWeek;

    const isEmpty = stats.entryCount === 0;
    tiles.hidden = isEmpty;
    body.hidden = isEmpty;
    note.hidden = isEmpty;
    empty.hidden = !isEmpty;
    if (isEmpty) {
      tiles.replaceChildren();
      rows.replaceChildren();
      columns.replaceChildren();
      return;
    }

    renderTiles(stats, isWeek);
    renderRows(stats, options);
    if (isWeek) {
      renderColumns(stats);
    } else {
      columns.replaceChildren();
    }
  }

  function renderTiles(
    stats: ReturnType<typeof computeStats>,
    isWeek: boolean
  ): void {
    tiles.replaceChildren();

    tiles.append(makeTile("Total", formatMinutes(stats.totalMinutes)));
    tiles.append(makeTile("Entries", String(stats.entryCount)));
    if (isWeek) {
      const bookedDays = stats.days.filter((day) => day.minutes > 0).length;
      const average =
        bookedDays === 0
          ? "–"
          : formatMinutes(Math.round(stats.totalMinutes / bookedDays));
      tiles.append(makeTile("Average per booked day", average));
    }
  }

  function renderRows(
    stats: ReturnType<typeof computeStats>,
    panelOptions: StatsPanelOptions
  ): void {
    rows.replaceChildren();
    const largest = stats.groups[0]?.minutes ?? 0;
    for (const group of stats.groups) {
      rows.append(makeRow(group, stats.totalMinutes, largest, panelOptions));
    }
  }

  function renderColumns(stats: ReturnType<typeof computeStats>): void {
    columns.replaceChildren();
    const largest = Math.max(...stats.days.map((day) => day.minutes), 0);
    for (const day of stats.days) {
      columns.append(makeColumn(day, largest));
    }
  }

  function makeTile(label: string, value: string): HTMLElement {
    const tile = document.createElement("div");
    tile.className = "stats-tile";
    const labelSpan = document.createElement("span");
    labelSpan.className = "stats-tile-label";
    labelSpan.textContent = label;
    const valueSpan = document.createElement("span");
    valueSpan.className = "stats-tile-value";
    valueSpan.textContent = value;
    tile.append(labelSpan, valueSpan);
    return tile;
  }

  function makeRow(
    group: GroupTotal,
    totalMinutes: number,
    largest: number,
    panelOptions: StatsPanelOptions
  ): HTMLElement {
    const share = totalMinutes > 0 ? Math.round((group.minutes / totalMinutes) * 100) : 0;
    const fullLabel = `${group.label}${group.detail !== null ? ` (${group.detail})` : ""}`;
    const valueText = `${formatMinutes(group.minutes)} · ${share}%`;

    const row = document.createElement("li");
    row.className = "stats-row";
    row.title = `${fullLabel}: ${formatMinutes(group.minutes)}, ${share}% of ${formatMinutes(totalMinutes)}`;

    const name = document.createElement("span");
    name.className = "stats-row-name";
    if (group.fileId !== null) {
      const swatch = document.createElement("span");
      swatch.className = "file-swatch";
      swatch.style.backgroundColor = panelOptions.colorForFile(group.fileId);
      swatch.setAttribute("aria-hidden", "true");
      name.append(swatch);
    }
    const nameText = document.createElement("span");
    nameText.textContent = group.label;
    name.append(nameText);
    if (group.detail !== null) {
      const detail = document.createElement("span");
      detail.className = "stats-row-detail";
      detail.textContent = group.detail;
      name.append(detail);
    }

    const barTrack = document.createElement("span");
    barTrack.className = "stats-row-bar";
    const bar = document.createElement("span");
    bar.className = "stats-bar";
    bar.setAttribute("aria-hidden", "true");
    bar.style.width = largest > 0 ? `${(group.minutes / largest) * 100}%` : "0%";
    barTrack.append(bar);

    const value = document.createElement("span");
    value.className = "stats-row-value";
    value.textContent = valueText;

    row.append(name, barTrack, value);
    return row;
  }

  function makeColumn(
    day: { date: Date; minutes: number },
    largest: number
  ): HTMLElement {
    const valueText = day.minutes === 0 ? "–" : formatMinutes(day.minutes);
    const column = document.createElement("div");
    column.className = "stats-column";
    column.title = `${day.date.toLocaleDateString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric"
    })}: ${valueText}`;

    const value = document.createElement("span");
    value.className = "stats-column-value";
    value.textContent = valueText;

    const track = document.createElement("span");
    track.className = "stats-column-track";
    if (day.minutes > 0 && largest > 0) {
      const bar = document.createElement("span");
      bar.className = "stats-column-bar";
      bar.setAttribute("aria-hidden", "true");
      bar.style.height = `${(day.minutes / largest) * 100}%`;
      track.append(bar);
    }

    const label = document.createElement("span");
    label.className = "stats-column-label";
    label.textContent = day.date.toLocaleDateString(undefined, {
      weekday: "short",
      day: "numeric"
    });

    column.append(value, track, label);
    return column;
  }

  return { element, update };
}

function readGroupBy(): GroupBy {
  const stored = window.localStorage.getItem(GROUP_BY_KEY);
  if (stored !== null && (GROUP_BY_VALUES as string[]).includes(stored)) {
    return stored as GroupBy;
  }
  return "file";
}
