import { createHeadingTree } from "./heading-selector";
import type { Heading } from "./api";

export interface EntryDialogOptions {
  fileId: string;
  headingId: string;
  outline: string[];
  title: string;
  start: Date;
  end: Date;
  timesEditable: boolean;
  /** Loads the headings for the tree. Called when the user clicks "Change heading…". */
  loadHeadings: () => Promise<Heading[]>;
  /** Called with the new values. Resolve to close the dialog; throw to keep it open. */
  onSave: (values: EntryDialogValues) => Promise<void>;
}

export interface EntryDialogValues {
  /** The new title, or null when "Rename…" is not active. */
  title: string | null;
  /** The target heading ID, or null when "Change heading…" is not active. */
  headingId: string | null;
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
  let mode: "none" | "rename" | "reassign" = "none";
  let targetHeadingId: string | null = null;
  let treeLoaded = false;

  const dialog = document.createElement("dialog");
  dialog.className = "clock-dialog";

  const heading = document.createElement("h2");
  heading.className = "clock-dialog-heading";
  heading.textContent = "Edit entry";

  const source = document.createElement("p");
  source.className = "clock-dialog-source";
  source.textContent = `${options.fileId}: ${options.outline.join(" / ")}`;

  const titleText = document.createElement("p");
  titleText.className = "clock-dialog-title";
  titleText.textContent = options.title;

  const actions = document.createElement("div");
  actions.className = "clock-dialog-actions";
  const renameButton = document.createElement("button");
  renameButton.type = "button";
  renameButton.className = "clock-dialog-button";
  renameButton.textContent = "Rename…";
  renameButton.setAttribute("aria-pressed", "false");
  const reassignButton = document.createElement("button");
  reassignButton.type = "button";
  reassignButton.className = "clock-dialog-button";
  reassignButton.textContent = "Change heading…";
  reassignButton.setAttribute("aria-pressed", "false");
  actions.append(renameButton, reassignButton);

  const renamePanel = document.createElement("div");
  renamePanel.hidden = true;
  const renameLabel = document.createElement("label");
  renameLabel.className = "clock-dialog-label";
  const renameLabelText = document.createElement("span");
  renameLabelText.textContent = "Title";
  const input = document.createElement("input");
  input.type = "text";
  input.name = "title";
  input.className = "clock-dialog-input";
  input.value = options.title;
  renameLabel.append(renameLabelText, input);
  const renameNote = document.createElement("p");
  renameNote.className = "clock-dialog-note";
  renameNote.textContent = "Renames the Org heading for all its entries, also on other days.";
  renamePanel.append(renameLabel, renameNote);

  const reassignPanel = document.createElement("div");
  reassignPanel.hidden = true;
  const targetText = document.createElement("p");
  targetText.className = "clock-dialog-target";
  targetText.textContent = "New heading: (none selected)";
  const treeContainer = document.createElement("div");
  treeContainer.className = "clock-dialog-tree";
  const reassignNote = document.createElement("p");
  reassignNote.className = "clock-dialog-note";
  reassignNote.textContent =
    "Moves only this entry to the selected heading. No heading is renamed.";
  reassignPanel.append(targetText, treeContainer, reassignNote);

  const form = document.createElement("form");
  form.className = "clock-dialog-form";

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
    reassignButton.disabled = true;
  }

  times.append(startLabel, endLabel);

  const duration = document.createElement("p");
  duration.className = "clock-dialog-duration";
  duration.setAttribute("aria-live", "polite");

  const note = document.createElement("p");
  note.className = "clock-dialog-note";
  note.textContent = "Changing start or end changes only this entry.";

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

  form.append(titleText, actions, renamePanel, reassignPanel, times, duration, note, errorArea, buttonRow);
  dialog.append(heading, source, form);
  document.body.append(dialog);

  const setMode = (next: "none" | "rename" | "reassign"): void => {
    mode = next;
    dialog.classList.toggle("clock-dialog-wide", mode === "reassign");
    renamePanel.hidden = mode !== "rename";
    reassignPanel.hidden = mode !== "reassign";
    renameButton.setAttribute("aria-pressed", mode === "rename" ? "true" : "false");
    reassignButton.setAttribute("aria-pressed", mode === "reassign" ? "true" : "false");
    renameButton.disabled = mode === "reassign";
    reassignButton.disabled = mode === "rename" || !options.timesEditable;
  };

  renameButton.addEventListener("click", () => {
    if (mode === "rename") {
      setMode("none");
      input.value = options.title;
      return;
    }
    setMode("rename");
    input.focus();
    input.select();
  });

  reassignButton.addEventListener("click", () => {
    if (mode === "reassign") {
      setMode("none");
      targetHeadingId = null;
      targetText.textContent = "New heading: (none selected)";
      return;
    }
    setMode("reassign");
    void loadTree();
  });

  const loadTree = async (): Promise<void> => {
    if (treeLoaded) {
      const search = treeContainer.querySelector<HTMLInputElement>(".heading-tree-search");
      search?.focus();
      return;
    }
    treeContainer.replaceChildren("Loading headings…");
    try {
      const headings = await options.loadHeadings();
      treeContainer.replaceChildren(
        createHeadingTree({
          headings,
          fileId: options.fileId,
          currentHeadingId: options.headingId,
          onSelect: (selected: Heading) => {
            targetHeadingId = selected.id;
            targetText.textContent = `New heading: ${selected.outline.join(" / ")}`;
          }
        })
      );
      treeLoaded = true;
    } catch (error: unknown) {
      console.error(error);
      errorArea.textContent = "Could not load headings";
      setMode("none");
      return;
    }
    const search = treeContainer.querySelector<HTMLInputElement>(".heading-tree-search");
    search?.focus();
  };

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
    if (mode === "reassign" && targetHeadingId === null) {
      errorArea.textContent = "Select a heading";
      return;
    }

    cancelButton.disabled = true;
    saveButton.disabled = true;
    errorArea.textContent = "";
    try {
      await options.onSave({
        title: mode === "rename" ? input.value : null,
        headingId: mode === "reassign" ? targetHeadingId : null,
        start,
        end
      });
      dialog.close();
    } catch (error: unknown) {
      errorArea.textContent =
        error instanceof Error ? error.message : "Could not save the entry";
      cancelButton.disabled = false;
      updateDuration();
    }
  }
}
