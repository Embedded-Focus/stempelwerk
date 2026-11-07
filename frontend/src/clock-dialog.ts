export interface EntryDialogOptions {
  fileId: string;
  outline: string[];
  title: string;
  /** Called with the new values. Resolve to close the dialog; reject to keep it open. */
  onSave: (values: EntryDialogValues) => Promise<void>;
}

export interface EntryDialogValues {
  title: string;
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

  const note = document.createElement("p");
  note.className = "clock-dialog-note";
  note.textContent =
    "This renames the Org heading. All entries of this heading show the new title, also on other days.";

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

  form.append(label, note, errorArea, buttonRow);
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

  dialog.showModal();
  input.select();

  async function handleSave(): Promise<void> {
    cancelButton.disabled = true;
    saveButton.disabled = true;
    errorArea.textContent = "";
    try {
      await options.onSave({ title: input.value });
      dialog.close();
    } catch (error: unknown) {
      errorArea.textContent =
        error instanceof Error ? error.message : "Could not save the entry";
      cancelButton.disabled = false;
      saveButton.disabled = false;
    }
  }
}
