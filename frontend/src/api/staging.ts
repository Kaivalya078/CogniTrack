// Types mirror backend/app/api/staging.py. Money arrives as strings to stay exact.

export type Fill = {
  label?: string | null;
  date: string | null;
  qty: number;
  price: string;
  charges: string;
  source: string;
};
export type Target = { label: string; price: string };
export type Payload = {
  account: string;
  strategy?: "momentum" | "long_term";
  symbol?: string;
  opened_on?: string | null;
  buys?: Fill[];
  exits?: Fill[];
  targets?: Target[];
  stop?: string | null;
  thesis?: string | null;
  review_trigger?: string | null;
  remarks?: string | null;
  amount?: string | null; // cash
  as_of?: string | null; // cash
};
export type Item = {
  id: number;
  row_ref: string;
  kind: "lot" | "cash";
  symbol: string | null;
  payload: Payload;
  match_status: "new" | "unchanged" | "changed" | "conflict";
  diff: string[];
  needs_input: string[];
  warnings: string[];
  status: "pending" | "skipped" | "committed";
  open_qty: number | null;
  realised: string | null;
  outcomes: string[];
};
export type BatchSummary = {
  id: number;
  importer: string;
  filename: string;
  status: "pending" | "committed" | "discarded";
  created_at: string;
};
export type Batch = BatchSummary & { items: Item[] };
export type ItemPatch = Partial<
  Pick<Payload, "opened_on" | "stop" | "targets" | "thesis" | "review_trigger" | "amount" | "as_of">
> & { status?: "pending" | "skipped" };

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(Array.isArray(detail) ? detail.join("; ") : typeof detail === "string" ? detail : `HTTP ${status}`);
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, body?.detail);
  return body as T;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const listBatches = () => request<BatchSummary[]>("/api/staging/batches");
export const getBatch = (id: number) => request<Batch>(`/api/staging/batches/${id}`);
export const uploadFile = (file: File) =>
  request<Batch>(`/api/staging/batches?filename=${encodeURIComponent(file.name)}`, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream" },
    body: file,
  });
export const patchItem = (id: number, patch: ItemPatch) =>
  request<Item>(`/api/staging/items/${id}`, json("PATCH", patch));
export const commitBatch = (id: number) => request<Batch>(`/api/staging/batches/${id}/commit`, json("POST"));
export const discardBatch = (id: number) =>
  request<BatchSummary>(`/api/staging/batches/${id}/discard`, json("POST"));
