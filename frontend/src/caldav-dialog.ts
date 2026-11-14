export interface CalDAVDialogOptions {
  title: string;
  start: Date;
  end: Date;
  allDay: boolean;
  calendarName: string;
  location: string | null;
}

const dateFormatter = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  year: "numeric",
  month: "short",
  day: "numeric"
});

const timeFormatter = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit"
});

function formatStartEnd(start: Date, end: Date, allDay: boolean): string {
  if (allDay) {
    // FullCalendar supplies an exclusive end for all-day events. Show the
    // inclusive last day instead, and a single date when it spans one day.
    const inclusiveEnd = new Date(end);
    inclusiveEnd.setDate(inclusiveEnd.getDate() - 1);
    if (sameDay(start, inclusiveEnd)) {
      return dateFormatter.format(start);
    }
    return `${dateFormatter.format(start)} – ${dateFormatter.format(inclusiveEnd)}`;
  }
  if (sameDay(start, end)) {
    return `${dateFormatter.format(start)} ${timeFormatter.format(start)} – ${timeFormatter.format(end)}`;
  }
  return `${dateFormatter.format(start)} ${timeFormatter.format(start)} – ${dateFormatter.format(end)} ${timeFormatter.format(end)}`;
}

function sameDay(first: Date, second: Date): boolean {
  return (
    first.getFullYear() === second.getFullYear() &&
    first.getMonth() === second.getMonth() &&
    first.getDate() === second.getDate()
  );
}

/**
 * Open a native read-only dialog for a CalDAV event.
 * It only displays details; it has no input, save, delete, or mutation action.
 */
export function openCalDAVDialog(options: CalDAVDialogOptions): void {
  const dialog = document.createElement("dialog");
  dialog.className = "caldav-dialog";

  const heading = document.createElement("h2");
  heading.className = "caldav-dialog-heading";
  heading.textContent = options.title;

  const times = document.createElement("p");
  times.className = "caldav-dialog-times";
  times.textContent = formatStartEnd(options.start, options.end, options.allDay);

  const calendar = document.createElement("p");
  calendar.className = "caldav-dialog-calendar";
  calendar.textContent = `Calendar: ${options.calendarName}`;

  dialog.append(heading, times, calendar);

  if (options.location !== null && options.location !== "") {
    const location = document.createElement("p");
    location.className = "caldav-dialog-location";
    location.textContent = `Location: ${options.location}`;
    dialog.append(location);
  }

  const buttonRow = document.createElement("div");
  buttonRow.className = "caldav-dialog-buttons";
  const closeButton = document.createElement("button");
  closeButton.type = "button";
  closeButton.className = "caldav-dialog-button";
  closeButton.textContent = "Close";
  closeButton.addEventListener("click", () => {
    dialog.close();
  });
  buttonRow.append(closeButton);
  dialog.append(buttonRow);

  // Native dialogs close on Escape via a cancel event; the close handler removes it.
  dialog.addEventListener("close", () => {
    dialog.remove();
  });

  document.body.append(dialog);
  dialog.showModal();
  closeButton.focus();
}
