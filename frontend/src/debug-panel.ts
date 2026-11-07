import { BackupError, createBackup, listBackups, type BackupInfo } from "./api";

export interface DebugPanelHooks {
  onStatus: (message: string) => void;
}

export function mountDebugPanel(
  appElement: HTMLElement,
  fileIds: string[],
  hooks: DebugPanelHooks
): () => void {
  const calendarElement = appElement.querySelector<HTMLElement>("#calendar");
  if (!calendarElement) {
    throw new Error("Calendar root not found");
  }

  const panel = document.createElement("section");
  panel.className = "debug-panel debug-collapsed";

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "debug-toggle";
  toggle.setAttribute("aria-expanded", "false");

  const arrow = document.createElement("span");
  arrow.className = "debug-toggle-arrow";
  arrow.textContent = "▾";
  arrow.setAttribute("aria-hidden", "true");

  const toggleText = document.createElement("span");
  toggleText.textContent = "Debug";

  toggle.append(arrow, toggleText);
  toggle.addEventListener("click", () => {
    const collapsed = panel.classList.toggle("debug-collapsed");
    toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
  });

  panel.append(toggle);

  if (fileIds.length === 0) {
    const empty = document.createElement("p");
    empty.className = "debug-empty";
    empty.textContent = "No configured files";
    panel.append(empty);
  }

  const backupLists: { fileId: string; list: HTMLUListElement }[] = [];
  for (const fileId of fileIds) {
    const section = buildFileSection(fileId, hooks);
    panel.append(section.element);
    backupLists.push({ fileId, list: section.list });
  }

  appElement.insertBefore(panel, calendarElement);

  return () => {
    for (const { fileId, list } of backupLists) {
      void refreshBackupList(fileId, list);
    }
  };
}

function buildFileSection(
  fileId: string,
  hooks: DebugPanelHooks
): { element: HTMLElement; list: HTMLUListElement } {
  const section = document.createElement("div");
  section.className = "debug-file";

  const label = document.createElement("span");
  label.className = "debug-file-id";
  label.textContent = fileId;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "debug-backup-button";
  button.textContent = "Create backup";

  const list = document.createElement("ul");
  list.className = "debug-backup-list";

  button.addEventListener("click", () => {
    void handleCreateBackup(fileId, list, button, hooks);
  });

  section.append(label, button, list);
  void refreshBackupList(fileId, list);
  return { element: section, list };
}

async function handleCreateBackup(
  fileId: string,
  list: HTMLUListElement,
  button: HTMLButtonElement,
  hooks: DebugPanelHooks
): Promise<void> {
  button.disabled = true;
  try {
    const backup = await createBackup(fileId);
    hooks.onStatus(`Backup created: ${backup.filename}`);
  } catch (error: unknown) {
    console.error(error);
    hooks.onStatus(
      error instanceof BackupError && error.status === 404
        ? "Unknown file"
        : "Could not create backup"
    );
  } finally {
    button.disabled = false;
  }
  await refreshBackupList(fileId, list);
}

async function refreshBackupList(fileId: string, list: HTMLUListElement): Promise<void> {
  let backups: BackupInfo[];
  try {
    backups = await listBackups(fileId);
  } catch (error: unknown) {
    console.error(error);
    return;
  }

  list.replaceChildren(...backups.map(renderBackupItem));
}

function renderBackupItem(backup: BackupInfo): HTMLLIElement {
  const item = document.createElement("li");
  item.className = "debug-backup-item";
  item.textContent = backup.filename;
  return item;
}
