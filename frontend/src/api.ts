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
