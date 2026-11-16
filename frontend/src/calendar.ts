import type {
  EventApi,
  EventDropArg,
  EventInput,
  EventMountArg,
  EventSourceFuncArg
} from "@fullcalendar/core";
import { Calendar } from "@fullcalendar/core";
import type { EventResizeDoneArg } from "@fullcalendar/interaction";
import interactionPlugin from "@fullcalendar/interaction";
import timeGridPlugin from "@fullcalendar/timegrid";

import {
  ClockUpdateError,
  HeadingRenameError,
  getStatus,
  listCalDAVEvents,
  listClocks,
  listHeadings,
  renameHeading,
  appendClock,
  splitClock,
  updateClock,
  type CalendarSource,
  type ClockEntry,
  type StatusResponse
} from "./api";
import { openCalDAVDialog } from "./caldav-dialog";
import {
  openEntryDialog,
  type EntryDialogValues
} from "./clock-dialog";
import { mountDebugPanel } from "./debug-panel";
import { createStatsPanel, type StatsEntry } from "./stats-panel";
import "./styles.css";

const debugEnabled =
  import.meta.env.VITE_DEBUG_PANEL === "1" ||
  new URLSearchParams(window.location.search).has("debug");

const calendarElement = document.querySelector<HTMLElement>("#calendar");
const appElement = document.querySelector<HTMLElement>("#app");

if (!calendarElement || !appElement) {
  throw new Error("Calendar root not found");
}

const toolbarElement = document.createElement("section");
toolbarElement.className = "toolbar";
toolbarElement.innerHTML = `
  <div class="source-filter" aria-label="Calendar sources"></div>
  <button class="reload-button" type="button">Reload</button>
  <span class="status-line" role="status"></span>
`;
appElement.insertBefore(toolbarElement, calendarElement);

const sourceFilterElement = toolbarElement.querySelector<HTMLElement>(".source-filter");
const reloadButton = toolbarElement.querySelector<HTMLButtonElement>(".reload-button");
const statusLine = toolbarElement.querySelector<HTMLElement>(".status-line");

if (!sourceFilterElement || !reloadButton || !statusLine) {
  throw new Error("Toolbar controls not found");
}

const sourceFilter = sourceFilterElement;
let selectedFileIds = new Set<string>();
let selectedCaldavIds = new Set<string>();
let orgSources: CalendarSource[] = [];
let caldavSources: CalendarSource[] = [];
let fileColors = new Map<string, string>();
let writeMode: StatusResponse["write_mode"] = "read-only";
let refreshCalDAVNext = false;

let dragActive = false;
let dragCancelRequested = false;
let refreshDebugPanel: () => void = () => {};

document.addEventListener("keydown", (event: KeyboardEvent) => {
  if (event.key !== "Escape" || !dragActive) {
    return;
  }
  dragCancelRequested = true;
  // End the drag the way a mouse release would. FullCalendar computes the
  // final mutation from the last hit and fires eventDrop/eventResize, where
  // the cancel flag makes us revert instead of saving.
  document.dispatchEvent(new MouseEvent("mouseup"));
});

const handleClockChange = async (info: EventDropArg | EventResizeDoneArg): Promise<void> => {
  const { event } = info;

  if (event.extendedProps.sourceKind !== "org") {
    info.revert();
    statusLine.textContent = "Calendar events cannot be changed";
    return;
  }

  if (dragCancelRequested) {
    dragCancelRequested = false;
    info.revert();
    statusLine.textContent = "Change cancelled";
    return;
  }

  const revision = event.extendedProps.revision;

  if (!event.start || !event.end || typeof revision !== "string") {
    info.revert();
    statusLine.textContent = "Could not update clock";
    return;
  }

  try {
    await updateClock({
      id: event.id,
      start: event.start.toISOString(),
      end: event.end.toISOString(),
      expectedRevision: revision
    });
    statusLine.textContent = "Clock updated";
    calendar.refetchEvents();
  } catch (error: unknown) {
    console.error(error);
    info.revert();
    if (error instanceof ClockUpdateError && error.status === 409) {
      statusLine.textContent = "Org file changed on disk - reloading calendar";
      calendar.refetchEvents();
    } else {
      statusLine.textContent = "Could not update clock";
    }
  }
};

const statsPanel = createStatsPanel({ colorForFile });

const calendar = new Calendar(calendarElement, {
  plugins: [interactionPlugin, timeGridPlugin],
  initialView: "timeGridWeek",
  firstDay: 1,
  nowIndicator: true,
  selectable: false,
  editable: true,
  eventStartEditable: true,
  eventDurationEditable: true,
  allDaySlot: false,
  slotDuration: "00:15:00",
  businessHours: {
    daysOfWeek: [1, 2, 3, 4, 5],
    startTime: "07:00",
    endTime: "20:00"
  },
  headerToolbar: {
    left: "prev,next today",
    center: "title",
    right: "timeGridDay,timeGridWeek"
  },
  events: async (info: EventSourceFuncArg): Promise<EventInput[]> => {
    statusLine.textContent = "Loading";

    const refresh = refreshCalDAVNext;
    refreshCalDAVNext = false;

    // Fetch both source kinds independently so one failure keeps the other's
    // events on the calendar. An empty Org selection resolves to no clocks;
    // calling the backend with no file_id would return every file's clocks.
    const [orgResult, caldavResult] = await Promise.allSettled([
      selectedFileIds.size > 0
        ? listClocks({
            start: info.startStr,
            end: info.endStr,
            fileIds: [...selectedFileIds]
          })
        : Promise.resolve({ clocks: [], revisions: {} }),
      selectedCaldavIds.size > 0
        ? listCalDAVEvents({
            start: info.startStr,
            end: info.endStr,
            calendarIds: [...selectedCaldavIds],
            refresh
          })
        : Promise.resolve({ events: [], errors: [] })
    ]);

    const warnings: string[] = [];
    let clockInputs: EventInput[] = [];
    let caldavInputs: EventInput[] = [];

    if (orgResult.status === "fulfilled") {
      clockInputs = orgResult.value.clocks.map((clock) => ({
        id: clock.id,
        title: clock.heading_title,
        start: clock.start,
        end: clock.end,
        backgroundColor: colorForFile(clock.file_id),
        borderColor: colorForFile(clock.file_id),
        textColor: textColorForBackground(colorForFile(clock.file_id)),
        editable: clock.editable,
        startEditable: clock.editable,
        durationEditable: clock.editable,
        extendedProps: {
          sourceKind: "org",
          fileId: clock.file_id,
          headingId: clock.heading_id,
          outline: clock.outline,
          revision: clock.revision,
          editable: clock.editable
        }
      }));
    } else {
      console.error(orgResult.reason);
      warnings.push("Org clocks unavailable");
    }

    if (caldavResult.status === "fulfilled") {
      caldavInputs = caldavResult.value.events.map((caldavEvent) => {
        const color = colorForCaldavId(caldavEvent.calendar_id);
        return {
          id: caldavEvent.id,
          title: caldavEvent.title,
          start: caldavEvent.start,
          end: caldavEvent.end,
          allDay: caldavEvent.all_day,
          backgroundColor: color,
          borderColor: color,
          textColor: textColorForBackground(color),
          editable: false,
          startEditable: false,
          durationEditable: false,
          extendedProps: {
            sourceKind: "caldav",
            calendarId: caldavEvent.calendar_id,
            calendarName: caldavEvent.calendar_name,
            location: caldavEvent.location
          }
        };
      });
      if (caldavResult.value.errors.length > 0) {
        const unavailableNames = caldavResult.value.errors
          .map((error) => caldavNameForId(error.calendar_id))
          .filter((name): name is string => name !== null);
        if (unavailableNames.length > 0) {
          warnings.push(`Calendar ${unavailableNames.join(", ")} unavailable`);
        } else {
          warnings.push("Calendar unavailable");
        }
      }
    } else {
      console.error(caldavResult.reason);
      warnings.push("Calendars unavailable");
    }

    const summary = `${clockInputs.length} clocks, ${caldavInputs.length} calendar events`;
    statusLine.textContent = warnings.length > 0 ? `${summary} - ${warnings.join("; ")}` : summary;
    return [...clockInputs, ...caldavInputs];
  },
  eventDidMount: (info: EventMountArg) => {
    const outline = info.event.extendedProps.outline;
    if (Array.isArray(outline)) {
      info.el.title = `${info.event.extendedProps.fileId}: ${outline.join(" / ")}`;
    }
    info.el.addEventListener("dblclick", (event: MouseEvent) => {
      event.preventDefault();
      handleEventOpen(info.event);
    });
  },
  eventDrop: (info: EventDropArg) => {
    void handleClockChange(info);
  },
  eventResize: (info: EventResizeDoneArg) => {
    void handleClockChange(info);
  },
  eventDragStart: () => {
    dragActive = true;
    dragCancelRequested = false;
  },
  eventDragStop: () => {
    dragActive = false;
  },
  eventResizeStart: () => {
    dragActive = true;
    dragCancelRequested = false;
  },
  eventResizeStop: () => {
    dragActive = false;
  },
  eventsSet: () => {
    updateStats();
  },
  datesSet: () => {
    updateStats();
  }
});

calendarElement.after(statsPanel.element);

const openCalDAVEventDialog = (event: EventApi): void => {
  const { calendarName, location } = event.extendedProps as {
    calendarName?: unknown;
    location?: unknown;
  };

  if (event.start === null || event.end === null || typeof calendarName !== "string") {
    statusLine.textContent = "Could not open the entry";
    return;
  }

  openCalDAVDialog({
    title: event.title,
    start: event.start,
    end: event.end,
    allDay: event.allDay,
    calendarName,
    location: typeof location === "string" ? location : null
  });
};

const handleEventOpen = (event: EventApi): void => {
  if (event.extendedProps.sourceKind === "caldav") {
    openCalDAVEventDialog(event);
    return;
  }

  if (writeMode === "read-only" || writeMode === "emacs") {
    statusLine.textContent = "Editing is not available in this write mode";
    return;
  }

  const { fileId, headingId, outline, revision, editable } = event.extendedProps as {
    fileId?: unknown;
    headingId?: unknown;
    outline?: unknown;
    revision?: unknown;
    editable?: unknown;
  };

  if (
    event.start === null ||
    event.end === null ||
    typeof fileId !== "string" ||
    typeof headingId !== "string" ||
    !Array.isArray(outline) ||
    typeof revision !== "string"
  ) {
    statusLine.textContent = "Could not open the entry";
    return;
  }

  const initialRevision = revision;
  let clockId = event.id;
  let revisionState = initialRevision;
  let savedStart = event.start;
  let savedEnd = event.end;
  const savedTitle = event.title;

  openEntryDialog({
    fileId,
    headingId,
    outline: outline.filter((part): part is string => typeof part === "string"),
    title: event.title,
    start: event.start,
    end: event.end,
    timesEditable: editable !== false,
    loadHeadings: listHeadings,
    onAppend: async () => {
      try {
        const appended: ClockEntry = await appendClock({
          id: clockId,
          expectedRevision: revisionState
        });
        revisionState = appended.revision;
        statusLine.textContent = "Entry appended";
        calendar.refetchEvents();
      } catch (error: unknown) {
        if (error instanceof ClockUpdateError && error.status === 409) {
          statusLine.textContent = "Org file changed on disk - reloading calendar";
          calendar.refetchEvents();
          return;
        }
        if (error instanceof ClockUpdateError && error.status === 404) {
          statusLine.textContent = "This entry no longer exists - reloading calendar";
          calendar.refetchEvents();
          return;
        }
        console.error(error);
        throw new Error("Could not append an entry");
      }
    },
    onSave: async ({ title, headingId: targetHeadingId, start, end, splitAt }: EntryDialogValues) => {
      if (splitAt !== null) {
        try {
          await splitClock({
            id: clockId,
            splitAt: splitAt.toISOString(),
            expectedRevision: revisionState
          });
          statusLine.textContent = "Entry split";
          calendar.refetchEvents();
        } catch (error: unknown) {
          if (error instanceof ClockUpdateError && error.status === 409) {
            statusLine.textContent = "Org file changed on disk - reloading calendar";
            calendar.refetchEvents();
            return;
          }
          if (error instanceof ClockUpdateError && error.status === 404) {
            statusLine.textContent = "This entry no longer exists - reloading calendar";
            calendar.refetchEvents();
            return;
          }
          if (
            error instanceof ClockUpdateError &&
            error.status === 422 &&
            error.code === "invalid_time_range"
          ) {
            throw new Error("The split time must be between the start and the end of the entry.");
          }
          console.error(error);
          throw new Error("Could not split the entry");
        }
        return;
      }

      const timesChanged =
        start.getTime() !== savedStart.getTime() || end.getTime() !== savedEnd.getTime();

      if (targetHeadingId !== null && targetHeadingId !== headingId) {
        try {
          await updateClock({
            id: clockId,
            start: start.toISOString(),
            end: end.toISOString(),
            expectedRevision: revisionState,
            headingId: targetHeadingId
          });
          statusLine.textContent = "Entry moved";
          calendar.refetchEvents();
        } catch (error: unknown) {
          if (error instanceof ClockUpdateError && error.status === 409) {
            statusLine.textContent = "Org file changed on disk - reloading calendar";
            calendar.refetchEvents();
            return;
          }
          if (error instanceof ClockUpdateError && error.status === 404) {
            if (error.code === "unknown_heading_id") {
              throw new Error(
                "The selected heading no longer exists. Close the dialog and try again."
              );
            }
            statusLine.textContent = "This entry no longer exists - reloading calendar";
            calendar.refetchEvents();
            return;
          }
          if (
            error instanceof ClockUpdateError &&
            error.status === 422 &&
            error.code === "invalid_time_range"
          ) {
            throw new Error("End must be at least one minute after start.");
          }
          console.error(error);
          throw new Error("Could not move the entry");
        }
        return;
      }

      const titleChanged = title !== null && title.trim() !== savedTitle;
      if (!timesChanged && !titleChanged) {
        return;
      }

      let timesSaved = false;
      if (timesChanged) {
        try {
          const updated: ClockEntry = await updateClock({
            id: clockId,
            start: start.toISOString(),
            end: end.toISOString(),
            expectedRevision: revisionState
          });
          clockId = updated.id;
          revisionState = updated.revision;
          savedStart = start;
          savedEnd = end;
          timesSaved = true;
        } catch (error: unknown) {
          if (error instanceof ClockUpdateError && error.status === 409) {
            statusLine.textContent = "Org file changed on disk - reloading calendar";
            calendar.refetchEvents();
            return;
          }
          if (error instanceof ClockUpdateError && error.status === 404) {
            statusLine.textContent = "This entry no longer exists - reloading calendar";
            calendar.refetchEvents();
            return;
          }
          if (
            error instanceof ClockUpdateError &&
            error.status === 422 &&
            error.code === "invalid_time_range"
          ) {
            throw new Error("End must be at least one minute after start.");
          }
          console.error(error);
          throw new Error("Could not save the times");
        }
      }

      if (titleChanged) {
        try {
          await renameHeading({
            fileId,
            headingId,
            title: title.trim(),
            expectedRevision: revisionState
          });
        } catch (error: unknown) {
          if (error instanceof HeadingRenameError && error.status === 409) {
            statusLine.textContent = timesSaved
              ? "Times saved, but the Org file changed on disk - reloading calendar"
              : "Org file changed on disk - reloading calendar";
            calendar.refetchEvents();
            return;
          }
          let message = "Could not rename heading";
          if (
            error instanceof HeadingRenameError &&
            error.status === 422 &&
            error.code === "invalid_title"
          ) {
            message =
              "This title cannot be stored as written. Check for line breaks, a leading uppercase word, or a trailing :tag:.";
          } else if (!(error instanceof HeadingRenameError)) {
            console.error(error);
          }
          if (timesSaved) {
            statusLine.textContent = `Times saved. ${message}`;
            calendar.refetchEvents();
          }
          throw new Error(message);
        }
      }

      statusLine.textContent = timesChanged && titleChanged
        ? "Entry updated"
        : timesChanged
          ? "Times updated"
          : "Heading renamed";
      calendar.refetchEvents();
    }
  });
}

function updateStats(): void {
  const view = calendar.view;
  const entries: StatsEntry[] = [];
  for (const event of calendar.getEvents()) {
    const { fileId, headingId, outline } = event.extendedProps;
    if (
      // Work statistics count only Org clocks, never CalDAV events.
      event.extendedProps.sourceKind !== "org" ||
      event.start === null ||
      event.end === null ||
      typeof fileId !== "string" ||
      typeof headingId !== "string" ||
      !Array.isArray(outline)
    ) {
      continue;
    }
    entries.push({
      start: event.start,
      end: event.end,
      fileId,
      headingId,
      title: event.title,
      outline: outline.filter((part): part is string => typeof part === "string")
    });
  }
  statsPanel.update({
    entries,
    rangeStart: view.activeStart,
    rangeEnd: view.activeEnd,
    rangeTitle: view.title,
    isWeek: view.type === "timeGridWeek"
  });
}

calendar.render();

reloadButton.addEventListener("click", () => {
  refreshCalDAVNext = true;
  calendar.refetchEvents();
  refreshDebugPanel();
});

void getStatus()
  .then((status) => {
    writeMode = status.write_mode;
    orgSources = status.sources.filter((source) => source.kind === "org");
    caldavSources = status.sources.filter((source) => source.kind === "caldav");
    selectedFileIds = new Set(orgSources.map((source) => source.id));
    selectedCaldavIds = new Set(caldavSources.map((source) => source.id));
    fileColors = new Map(Object.entries(status.file_colors));
    renderSourceFilter();
    calendar.setOption("allDaySlot", caldavSources.length > 0);
    statusLine.textContent = status.sources.length === 0 ? "No configured sources" : "Ready";
    if (debugEnabled) {
      refreshDebugPanel = mountDebugPanel(appElement, status.files, {
        onStatus: (message: string) => {
          statusLine.textContent = message;
        }
      });
    }
    calendar.refetchEvents();
  })
  .catch((error: unknown) => {
    console.error(error);
    statusLine.textContent = "Backend unavailable";
  });

function renderSourceFilter(): void {
  sourceFilter.replaceChildren();

  if (orgSources.length === 0 && caldavSources.length === 0) {
    const empty = document.createElement("span");
    empty.className = "empty-sources";
    empty.textContent = "No configured sources";
    sourceFilter.append(empty);
    return;
  }

  if (orgSources.length > 0) {
    sourceFilter.append(
      renderFilterGroup("Org files", orgSources, (source) => {
        if (selectedFileIds.has(source.id)) {
          selectedFileIds.delete(source.id);
        } else {
          selectedFileIds.add(source.id);
        }
        calendar.refetchEvents();
      })
    );
  }

  if (caldavSources.length > 0) {
    sourceFilter.append(
      renderFilterGroup("Calendars", caldavSources, (source) => {
        if (selectedCaldavIds.has(source.id)) {
          selectedCaldavIds.delete(source.id);
        } else {
          selectedCaldavIds.add(source.id);
        }
        calendar.refetchEvents();
      })
    );
  }
}

function renderFilterGroup(
  groupLabel: string,
  sources: CalendarSource[],
  onToggle: (source: CalendarSource) => void
): HTMLElement {
  const group = document.createElement("div");
  group.className = "filter-group";

  const heading = document.createElement("span");
  heading.className = "filter-group-label";
  heading.textContent = groupLabel;
  group.append(heading);

  for (const source of sources) {
    const label = document.createElement("label");
    label.className = "file-option";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = source.id;
    checkbox.checked =
      source.kind === "org" ? selectedFileIds.has(source.id) : selectedCaldavIds.has(source.id);
    checkbox.addEventListener("change", () => {
      onToggle(source);
    });

    const text = document.createElement("span");
    text.textContent = source.name;

    const swatch = document.createElement("span");
    swatch.className = "file-swatch";
    swatch.style.backgroundColor = colorForSource(source);
    swatch.setAttribute("aria-hidden", "true");

    label.append(checkbox, swatch, text);
    group.append(label);
  }

  return group;
}

function colorForFile(fileId: string): string {
  return fileColors.get(fileId) ?? fallbackColor(fileId);
}

function colorForSource(source: CalendarSource): string {
  return source.color ?? fallbackColor(source.id);
}

function colorForCaldavId(calendarId: string): string {
  const source = caldavSources.find((entry) => entry.id === calendarId);
  return source !== undefined ? colorForSource(source) : fallbackColor(calendarId);
}

function caldavNameForId(calendarId: string): string | null {
  return caldavSources.find((entry) => entry.id === calendarId)?.name ?? null;
}

function fallbackColor(fileId: string): string {
  const palette = ["#2563eb", "#16a34a", "#dc2626", "#9333ea", "#ca8a04", "#0891b2"];
  let hash = 0;
  for (const char of fileId) {
    hash = (hash * 31 + char.charCodeAt(0)) % palette.length;
  }
  return palette[hash];
}

function textColorForBackground(hexColor: string): string {
  const red = Number.parseInt(hexColor.slice(1, 3), 16);
  const green = Number.parseInt(hexColor.slice(3, 5), 16);
  const blue = Number.parseInt(hexColor.slice(5, 7), 16);
  const luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255;
  return luminance > 0.62 ? "#111827" : "#ffffff";
}
