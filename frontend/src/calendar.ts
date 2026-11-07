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
  listClocks,
  renameHeading,
  updateClock,
  type StatusResponse
} from "./api";
import { openRenameDialog } from "./clock-dialog";
import { mountDebugPanel } from "./debug-panel";
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
  <div class="file-filter" aria-label="Org files"></div>
  <button class="reload-button" type="button">Reload</button>
  <span class="status-line" role="status"></span>
`;
appElement.insertBefore(toolbarElement, calendarElement);

const fileFilterElement = toolbarElement.querySelector<HTMLElement>(".file-filter");
const reloadButton = toolbarElement.querySelector<HTMLButtonElement>(".reload-button");
const statusLine = toolbarElement.querySelector<HTMLElement>(".status-line");

if (!fileFilterElement || !reloadButton || !statusLine) {
  throw new Error("Toolbar controls not found");
}

const fileFilter = fileFilterElement;
let selectedFileIds = new Set<string>();
let fileColors = new Map<string, string>();
let writeMode: StatusResponse["write_mode"] = "read-only";

let dragActive = false;
let dragCancelRequested = false;

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
    try {
      const response = await listClocks({
        start: info.startStr,
        end: info.endStr,
        fileIds: [...selectedFileIds]
      });
      statusLine.textContent = `${response.clocks.length} clocks`;
      return response.clocks.map((clock) => ({
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
          fileId: clock.file_id,
          headingId: clock.heading_id,
          outline: clock.outline,
          revision: clock.revision
        }
      }));
    } catch (error: unknown) {
      console.error(error);
      statusLine.textContent = "Could not load clocks";
      return [];
    }
  },
  eventDidMount: (info: EventMountArg) => {
    const outline = info.event.extendedProps.outline;
    if (Array.isArray(outline)) {
      info.el.title = `${info.event.extendedProps.fileId}: ${outline.join(" / ")}`;
    }
    info.el.addEventListener("dblclick", (event: MouseEvent) => {
      event.preventDefault();
      handleEventClick(info.event);
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
  }
});

const handleEventClick = (event: EventApi): void => {
  if (writeMode === "read-only" || writeMode === "emacs") {
    statusLine.textContent = "Renaming is not available in this write mode";
    return;
  }

  const { fileId, headingId, outline, revision } = event.extendedProps as {
    fileId?: unknown;
    headingId?: unknown;
    outline?: unknown;
    revision?: unknown;
  };

  if (
    typeof fileId !== "string" ||
    typeof headingId !== "string" ||
    !Array.isArray(outline) ||
    typeof revision !== "string"
  ) {
    statusLine.textContent = "Could not rename heading";
    return;
  }

  openRenameDialog({
    fileId,
    outline: outline.filter((part): part is string => typeof part === "string"),
    title: event.title,
    onSave: async (title: string) => {
      try {
        await renameHeading({
          fileId,
          headingId,
          title,
          expectedRevision: revision
        });
        statusLine.textContent = "Heading renamed";
        calendar.refetchEvents();
      } catch (error: unknown) {
        if (error instanceof HeadingRenameError && error.status === 409) {
          statusLine.textContent = "Org file changed on disk - reloading calendar";
          calendar.refetchEvents();
          return;
        }
        if (error instanceof HeadingRenameError && error.status === 422 && error.code === "invalid_title") {
          throw new Error(
            "This title cannot be stored as written. Check for line breaks, a leading uppercase word, or a trailing :tag:."
          );
        }
        console.error(error);
        throw new Error("Could not rename heading");
      }
    }
  });
}

calendar.render();

reloadButton.addEventListener("click", () => {
  calendar.refetchEvents();
});

void getStatus()
  .then((status) => {
    writeMode = status.write_mode;
    selectedFileIds = new Set(status.files);
    fileColors = new Map(Object.entries(status.file_colors));
    renderFileFilter(status.files);
    statusLine.textContent = status.files.length === 0 ? "No configured files" : "Ready";
    if (debugEnabled) {
      mountDebugPanel(appElement, status.files, {
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

function renderFileFilter(fileIds: string[]): void {
  fileFilter.replaceChildren();

  if (fileIds.length === 0) {
    const empty = document.createElement("span");
    empty.className = "empty-files";
    empty.textContent = "No configured files";
    fileFilter.append(empty);
    return;
  }

  for (const fileId of fileIds) {
    const label = document.createElement("label");
    label.className = "file-option";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = fileId;
    checkbox.checked = selectedFileIds.has(fileId);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        selectedFileIds.add(fileId);
      } else {
        selectedFileIds.delete(fileId);
      }
      calendar.refetchEvents();
    });

    const text = document.createElement("span");
    text.textContent = fileId;

    const swatch = document.createElement("span");
    swatch.className = "file-swatch";
    swatch.style.backgroundColor = colorForFile(fileId);
    swatch.setAttribute("aria-hidden", "true");

    label.append(checkbox, swatch, text);
    fileFilter.append(label);
  }
}

function colorForFile(fileId: string): string {
  return fileColors.get(fileId) ?? fallbackColor(fileId);
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
