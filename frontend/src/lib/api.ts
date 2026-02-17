const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

// ── Libraries ──

export interface Library {
  id: string;
  name: string;
  description: string;
  is_active: boolean;
  doc_count: number;
  chunk_count: number;
  status: string;
  build_progress: number;
  created_at: string;
  updated_at: string;
}

export const getLibraries = () => request<Library[]>("/api/libraries");
export const createLibrary = (name: string, description = "") =>
  request<Library>("/api/libraries", {
    method: "POST",
    body: JSON.stringify({ name, description }),
  });
export const deleteLibrary = (id: string) =>
  request(`/api/libraries/${id}`, { method: "DELETE" });
export const activateLibrary = (id: string) =>
  request(`/api/libraries/${id}/activate`, { method: "POST" });
export const startBuild = (id: string) =>
  request<{ job_id: string }>(`/api/libraries/${id}/build`, { method: "POST" });
export const getBuildStatus = (id: string) =>
  request<{
    job_id: string;
    status: string;
    current_step: string;
    progress: number;
    steps_completed: string[];
    error: string | null;
  }>(`/api/libraries/${id}/build/status`);
export const cancelBuild = (id: string) =>
  request(`/api/libraries/${id}/build/cancel`, { method: "POST" });

// ── Sources ──

export interface Source {
  id: string;
  library_id: string;
  source_type: string;
  config: Record<string, unknown>;
  doc_count: number;
  last_synced: string | null;
  created_at: string;
}

export const getSources = (libId: string) =>
  request<Source[]>(`/api/libraries/${libId}/sources`);
export const addSource = (libId: string, source_type: string, config: Record<string, unknown>) =>
  request<Source>(`/api/libraries/${libId}/sources`, {
    method: "POST",
    body: JSON.stringify({ source_type, config }),
  });
export const deleteSource = (id: string) =>
  request(`/api/sources/${id}`, { method: "DELETE" });
export const syncSource = (id: string) =>
  request(`/api/sources/${id}/sync`, { method: "POST" });

// ── Folder Browser ──

export interface BrowseEntry {
  name: string;
  path: string;
  type: "directory" | "file";
  file_count?: number;
  size?: number;
}

export interface BrowseResult {
  current_path: string;
  parent_path: string | null;
  entries: BrowseEntry[];
  supported_files: number;
}

export const browseFolders = (path = "~") =>
  request<BrowseResult>(`/api/browse?path=${encodeURIComponent(path)}`);

// ── ChromaDB Connector ──

export interface ChromaProbeResult {
  valid: boolean;
  collections?: { name: string; count: number }[];
  total_chunks?: number;
  path?: string;
  error?: string;
}

export const probeChromaDB = (path: string) =>
  request<ChromaProbeResult>("/api/probe-chromadb", {
    method: "POST",
    body: JSON.stringify({ path }),
  });

export const connectChromaDB = (libId: string, path: string) =>
  request<Source & { collections: { name: string; count: number }[]; total_chunks: number }>(
    `/api/libraries/${libId}/connect-chromadb`,
    {
      method: "POST",
      body: JSON.stringify({ source_type: "chromadb", config: { path } }),
    }
  );

export interface UploadResultItem {
  status: "success" | "skipped" | "error";
  file: string;
  reason?: string;
  error?: string;
}

export interface UploadResult {
  results: UploadResultItem[];
  summary?: {
    total: number;
    success: number;
    errors: number;
    skipped: number;
  };
}

export const uploadFiles = async (libId: string, files: File[]) => {
  const formData = new FormData();
  files.forEach((f) => formData.append("files", f));
  const res = await fetch(`${API_URL}/api/libraries/${libId}/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Upload failed" }));
    throw new Error(err.detail || "Upload failed");
  }
  return res.json() as Promise<UploadResult>;
};

// ── Verify ──

export interface VerdictItem {
  claim: string;
  claim_type: string;
  verdict: string;
  confidence: number;
  reason?: string;
  reasoning: string;
  used_llm?: boolean;
  evidence?: {
    text: string;
    source: string;
    page: number | null;
  } | null;
  evidence_used: string;
  contradiction_type: string | null;
  contradiction_explanation: string | null;
  sources: { document_title: string; page: number | null; paragraph: number | null }[];
  temporal_context: Record<string, unknown> | null;
}

export interface VerifyResult {
  verification_id: string;
  trust_score: number;
  total_claims: number;
  supported: number;
  partially_supported: number;
  contradicted: number;
  conflicting: number;
  no_evidence: number;
  verdicts: VerdictItem[];
}

export const verifyText = (text: string, library_id?: string) =>
  request<VerifyResult>("/api/verify", {
    method: "POST",
    body: JSON.stringify({ text, library_id }),
  });

export interface HistoryItem {
  id: string;
  library_id: string;
  input_text: string;
  trust_score: number;
  claim_count: number;
  created_at: string;
}

export const getHistory = (library_id?: string) =>
  request<HistoryItem[]>(`/api/verify/history${library_id ? `?library_id=${library_id}` : ""}`);
export const getVerification = (id: string) =>
  request<{ id: string; input_text: string; trust_score: number; claims: VerdictItem[]; created_at: string }>(
    `/api/verify/${id}`
  );
export const deleteVerification = async (id: string) => {
  const delRes = await fetch(`${API_URL}/api/verify/${id}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
  });

  if (delRes.ok) {
    return delRes.json();
  }

  // Fallback for environments where DELETE is blocked.
  if (delRes.status === 405) {
    return request<{ status: string; id: string }>(`/api/verify/${id}/delete`, { method: "POST" });
  }

  const err = await delRes.json().catch(() => ({ detail: delRes.statusText }));
  throw new Error(err.detail || delRes.statusText);
};

// ── Settings ──

export const getSettings = () => request<{ llm: Record<string, unknown>; connections: Record<string, unknown> }>("/api/settings");
export const updateLLMSettings = (config: Record<string, unknown>) =>
  request("/api/settings/llm", { method: "PUT", body: JSON.stringify(config) });
export const testLLM = () => request<{ status: string; message?: string; error?: string }>("/api/settings/llm/test", { method: "POST" });
export const testConnection = (config: Record<string, unknown>) =>
  request<{ status: string; message?: string; error?: string }>("/api/settings/connections/test", {
    method: "POST",
    body: JSON.stringify(config),
  });

// ── Health ──

export const getHealth = () =>
  request<{
    status: string;
    active_library: { id: string; name: string; doc_count: number; chunk_count: number; status: string } | null;
  }>("/api/health");
