export interface EntryDialogOptions {
  fileId: string;
  outline: string[];
  title: string;
  start: Date;
  end: Date;
  /** False disables the start and end inputs. */
  timesEditable: boolean;
  /** Called with the new values. Resolve to close the dialog; throw to keep it open. */
  onSave: (values: EntryDialogValues) => Promise<void>;
}

export interface EntryDialogValues {
  title: string;
  start: Date;
  end: Date;
}

/** Format a Date as "YYYY-MM-DDTHH:MM" in the browser's local time zone. */
function toLocalInputValue(date: Date): string {
  const pad = (value: number): string => String(value).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

/** Parse a datetime-local value as local time. Return null if it is invalid. */
function fromLocalInputValue(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(value)) {
    return null;
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Format minutes as Org does, for example 75 -> "1:15". */
function formatDuration(totalMinutes: number): string {
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return `${hours}:${String(minutes).padStart(2, "0")}`;
}

export function openEntryDialog(options: EntryDialogOptions): void {
  const dialog = document.createElement("dialog");
  dialog.className = "clock-dialog";

  const heading = document.createElement("h2");
  heading.className = "clock-dialog-heading";
  heading.textContent = "Edit entry";

  const source = document.createElement("p");
  source.className = "clock-dialog-source";
  source.textContent = `${options.fileId}: ${options.outline.join(" / ")}`;

  const form = document.createElement("form");
  form.className = "clock-dialog-form";

  const label = document.createElement("label");
  label.className = "clock-dialog-label";
  const labelText = document.createElement("span");
  labelText.textContent = "Title";
  const input = document.createElement("input");
  input.type = "text";
  input.name = "title";
  input.className = "clock-dialog-input";
  input.value = options.title;
  label.append(labelText, input);

  const times = document.createElement("div");
  times.className = "clock-dialog-times";

  const startLabel = document.createElement("label");
  startLabel.className = "clock-dialog-label";
  const startText = document.createElement("span");
  startText.textContent = "Start";
  const startInput = document.createElement("input");
  startInput.type = "datetime-local";
  startInput.step = "60";
  startInput.name = "start";
  startInput.required = true;
  startInput.className = "clock-dialog-input";
  startInput.value = toLocalInputValue(options.start);
  startLabel.append(startText, startInput);

  const endLabel = document.createElement("label");
  endLabel.className = "clock-dialog-label";
  const endText = document.createElement("span");
  endText.textContent = "End";
  const endInput = document.createElement("input");
  endInput.type = "datetime-local";
  endInput.step = "60";
  endInput.name = "end";
  endInput.required = true;
  endInput.className = "clock-dialog-input";
  endInput.value = toLocalInputValue(options.end);
  endLabel.append(endText, endInput);

  if (!options.timesEditable) {
    startInput.disabled = true;
    endInput.disabled = true;
  }

  times.append(startLabel, endLabel);

  const duration = document.createElement("p");
  duration.className = "clock-dialog-duration";
  duration.setAttribute("aria-live", "polite");

  const note = document.createElement("p");
  note.className = "clock-dialog-note";
  note.textContent =
    "Changing the title renames the Org heading for all its entries, also on other days. Changing start or end changes only this entry.";

  const errorArea = document.createElement("p");
  errorArea.className = "clock-dialog-error";
  errorArea.setAttribute("role", "alert");

  const buttonRow = document.createElement("div");
  buttonRow.className = "clock-dialog-buttons";
  const cancelButton = document.createElement("button");
  cancelButton.type = "button";
  cancelButton.className = "clock-dialog-button";
  cancelButton.textContent = "Cancel";
  const saveButton = document.createElement("button");
  saveButton.type = "submit";
  saveButton.className = "clock-dialog-button clock-dialog-button-primary";
  saveButton.textContent = "Save";
  buttonRow.append(cancelButton, saveButton);

  form.append(label, times, duration, note, errorArea, buttonRow);
  dialog.append(heading, source, form);
  document.body.append(dialog);

  cancelButton.addEventListener("click", () => {
    dialog.close();
  });

  form.addEventListener("submit", (event: SubmitEvent) => {
    event.preventDefault();
    void handleSave();
  });

  dialog.addEventListener("close", () => {
    dialog.remove();
  });

  const updateDuration = (): void => {
    const start = fromLocalInputValue(startInput.value);
    const end = fromLocalInputValue(endInput.value);
    if (start === null || end === null) {
      duration.textContent = "Enter a start and an end";
      saveButton.disabled = true;
      return;
    }
    if (end.getTime() <= start.getTime()) {
      duration.textContent = "End must be after start";
      saveButton.disabled = true;
      return;
    }
    const minutes = Math.round((end.getTime() - start.getTime()) / 60000);
    duration.textContent = `Duration: ${formatDuration(minutes)}`;
    saveButton.disabled = false;
  };

  startInput.addEventListener("input", updateDuration);
  endInput.addEventListener("input", updateDuration);
  updateDuration();

  dialog.showModal();
  input.select();

  async function handleSave(): Promise<void> {
    const start = fromLocalInputValue(startInput.value);
    const end = fromLocalInputValue(endInput.value);
    if (start === null || end === null) {
      errorArea.textContent = "Enter a start and an end";
      return;
    }
    if (end.getTime() <= start.getTime()) {
      errorArea.textContent = "End must be after start";
      return;
    }

    cancelButton.disabled = true;
    saveButton.disabled = true;
    errorArea.textContent = "";
    try {
      await options.onSave({ title: input.value, start, end });
      dialog.close();
    } catch (error: unknown) {
      errorArea.textContent =
        error instanceof Error ? error.message : "Could not save the entry";
      cancelButton.disabled = false;
      updateDuration();
    }
  }
}
