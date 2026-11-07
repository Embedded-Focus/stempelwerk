export interface StatusResponse {
  status: "ok";
  emacs_available: boolean;
  write_mode: "auto" | "emacs" | "disk" | "read-only";
  timezone: string;
  files: string[];
  file_colors: Record<string, string>;
}

export interface ClockEntry {
  id: string;
  file_id: string;
  heading_id: string;
  heading_title: string;
  outline: string[];
  start: string;
  end: string;
  duration_minutes: number;
  revision: string;
  editable: boolean;
}

export interface ClockEntriesResponse {
  clocks: ClockEntry[];
  revisions: Record<string, string>;
}

export async function getStatus(): Promise<StatusResponse> {
  const response = await fetch("/api/v1/status");
  if (!response.ok) {
    throw new Error(`Status request failed: ${response.status}`);
  }
  return response.json() as Promise<StatusResponse>;
}

export async function listClocks(params: {
  start: string;
  end: string;
  fileIds: string[];
}): Promise<ClockEntriesResponse> {
  const searchParams = new URLSearchParams({
    start: params.start,
    end: params.end
  });

  for (const fileId of params.fileIds) {
    searchParams.append("file_id", fileId);
  }

  const response = await fetch(`/api/v1/clocks?${searchParams}`);
  if (!response.ok) {
    throw new Error(`Clock request failed: ${response.status}`);
  }
  return response.json() as Promise<ClockEntriesResponse>;
}

export class ClockUpdateError extends Error {
  status: number;

  constructor(status: number) {
    super(`Clock update failed: ${status}`);
    this.status = status;
  }
}

export class BackupError extends Error {
  status: number;

  constructor(status: number) {
    super(`Backup request failed: ${status}`);
    this.status = status;
  }
}

export interface BackupInfo {
  file_id: string;
  filename: string;
  created_at: string;
}

export async function createBackup(fileId: string): Promise<BackupInfo> {
  const response = await fetch(`/api/v1/files/${encodeURIComponent(fileId)}/backups`, {
    method: "POST"
  });

  if (!response.ok) {
    throw new BackupError(response.status);
  }
  return response.json() as Promise<BackupInfo>;
}

export async function listBackups(fileId: string): Promise<BackupInfo[]> {
  const response = await fetch(`/api/v1/files/${encodeURIComponent(fileId)}/backups`);

  if (!response.ok) {
    throw new BackupError(response.status);
  }
  const body = (await response.json()) as { backups: BackupInfo[] };
  return body.backups;
}

export async function updateClock(params: {
  id: string;
  start: string;
  end: string;
  expectedRevision: string;
}): Promise<void> {
  const response = await fetch(`/api/v1/clocks/${encodeURIComponent(params.id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      start: params.start,
      end: params.end,
      expected_revision: params.expectedRevision
    })
  });

  if (!response.ok) {
    throw new ClockUpdateError(response.status);
  }
}
