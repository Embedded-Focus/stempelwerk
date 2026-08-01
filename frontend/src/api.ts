export interface StatusResponse {
  status: "ok";
  emacs_available: boolean;
  write_mode: "auto" | "emacs" | "disk" | "read-only";
  timezone: string;
  files: string[];
}

export async function getStatus(): Promise<StatusResponse> {
  const response = await fetch("/api/v1/status");
  if (!response.ok) {
    throw new Error(`Status request failed: ${response.status}`);
  }
  return response.json() as Promise<StatusResponse>;
}

