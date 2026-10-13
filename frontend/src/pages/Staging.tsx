import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  commitBatch,
  discardBatch,
  getBatch,
  listBatches,
  patchItem,
  uploadFile,
  type Batch,
  type Item,
  type ItemPatch,
  type Target,
} from "../api/staging";

// Display only: the numbers themselves stay strings from the API.
const inr = (s: string | null | undefined) =>
  s == null ? "–" : `₹${Number(s).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const BADGE: Record<string, string> = {
  new: "bg-blue-100 text-blue-900",
  changed: "bg-amber-100 text-amber-900",
  conflict: "bg-red-100 text-red-900",
  unchanged: "bg-gray-100 text-gray-700",
  target: "bg-green-100 text-green-900",
  breakeven: "bg-gray-100 text-gray-700",
  stop: "bg-red-100 text-red-900",
  early_exit: "bg-amber-100 text-amber-900",
  loss: "bg-red-100 text-red-900",
};

function Badge({ text }: { text: string }) {
  return <span className={`rounded px-1.5 py-0.5 text-xs ${BADGE[text] ?? "bg-gray-100"}`}>{text.replace("_", " ")}</span>;
}

export default function Staging() {
  const queryClient = useQueryClient();
  const batches = useQuery({ queryKey: ["batches"], queryFn: listBatches });
  const [chosen, setChosen] = useState<number | null>(null);
  const batchId = chosen ?? batches.data?.find((b) => b.status === "pending")?.id ?? null;

  const upload = useMutation({
    mutationFn: uploadFile,
    onSuccess: (batch) => {
      queryClient.setQueryData(["batch", batch.id], batch);
      queryClient.invalidateQueries({ queryKey: ["batches"] });
      setChosen(batch.id);
    },
  });

  return (
    <section className="space-y-4">
      <label className="block rounded-lg border border-dashed border-gray-400 p-4 text-center text-sm">
        <span className="font-medium">Upload</span> the momentum sheet or a Groww order history (.xlsx)
        <input
          type="file"
          accept=".xlsx"
          className="sr-only"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload.mutate(file);
            e.target.value = "";
          }}
        />
      </label>
      {upload.isPending && <p className="text-sm">Reading…</p>}
      {upload.error && <p className="text-sm text-red-700">{upload.error.message}</p>}

      {!!batches.data?.length && (
        <select
          className="w-full rounded border p-2 text-sm"
          value={batchId ?? ""}
          onChange={(e) => setChosen(Number(e.target.value))}
        >
          <option value="" disabled>
            Choose a batch
          </option>
          {batches.data.map((b) => (
            <option key={b.id} value={b.id}>
              #{b.id} {b.filename} · {b.status} · {new Date(b.created_at).toLocaleString("en-IN")}
            </option>
          ))}
        </select>
      )}
      {batchId != null && <BatchView id={batchId} />}
    </section>
  );
}

function BatchView({ id }: { id: number }) {
  const queryClient = useQueryClient();
  const { data: batch, error } = useQuery({ queryKey: ["batch", id], queryFn: () => getBatch(id) });
  const refresh = (b?: Batch) => {
    if (b) queryClient.setQueryData(["batch", id], b);
    queryClient.invalidateQueries({ queryKey: ["batches"] });
    queryClient.invalidateQueries({ queryKey: ["batch", id] });
  };
  const commit = useMutation({ mutationFn: () => commitBatch(id), onSuccess: refresh });
  // Cards with typed but unsaved values: committing now would silently drop them.
  const [unsaved, setUnsaved] = useState<ReadonlySet<number>>(new Set());
  const markUnsaved = useCallback((itemId: number, dirty: boolean) => {
    setUnsaved((prev) => {
      if (prev.has(itemId) === dirty) return prev;
      const next = new Set(prev);
      if (dirty) next.add(itemId);
      else next.delete(itemId);
      return next;
    });
  }, []);
  const discard = useMutation({ mutationFn: () => discardBatch(id), onSuccess: () => refresh() });

  if (error) return <p className="text-sm text-red-700">{error.message}</p>;
  if (!batch) return <p className="text-sm">Loading…</p>;

  const pending = batch.items.filter((i) => i.status === "pending");
  const blocking = pending.filter((i) => i.needs_input.length || i.match_status === "conflict");
  const unchanged = batch.items.filter((i) => i.match_status === "unchanged" && !i.needs_input.length);
  const rest = batch.items.filter((i) => !unchanged.includes(i));
  const editable = batch.status === "pending";
  const commitProblems = commit.error instanceof ApiError && Array.isArray(commit.error.detail) ? commit.error.detail : null;

  return (
    <div className="space-y-3">
      <div className="rounded-lg border p-3 text-sm">
        <div className="font-medium">
          {batch.filename} <span className="text-gray-500">({batch.importer})</span>
        </div>
        <div className="text-gray-600">
          {batch.status} · {pending.length} pending · {blocking.length} blocking · {unchanged.length} unchanged
        </div>
        {editable && (
          <div className="mt-2 flex gap-2">
            <button
              className="rounded bg-gray-900 px-3 py-1.5 text-white disabled:opacity-40"
              disabled={blocking.length > 0 || unsaved.size > 0 || commit.isPending}
              onClick={() => commit.mutate()}
            >
              Commit to ledger
            </button>
            <button className="rounded border px-3 py-1.5" onClick={() => discard.mutate()}>
              Discard
            </button>
          </div>
        )}
        {editable && unsaved.size > 0 && (
          <p className="mt-2 font-medium text-amber-800">
            Press Save on the {unsaved.size === 1 ? "card" : `${unsaved.size} cards`} you edited before
            committing.
          </p>
        )}
        {commitProblems ? (
          <ul className="mt-2 list-disc pl-5 text-red-700">
            {commitProblems.map((p) => (
              <li key={String(p)}>{String(p)}</li>
            ))}
          </ul>
        ) : (
          commit.error && <p className="mt-2 text-red-700">{commit.error.message}</p>
        )}
      </div>

      {rest.map((item) => (
        <ItemCard key={item.id} item={item} batchId={id} editable={editable} onDirty={markUnsaved} />
      ))}
      {unchanged.length > 0 && (
        <details className="rounded-lg border p-3 text-sm">
          <summary>{unchanged.length} unchanged (already in the ledger)</summary>
          <div className="mt-2 space-y-2">
            {unchanged.map((item) => (
              <ItemCard key={item.id} item={item} batchId={id} editable={false} onDirty={markUnsaved} />
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

type OnDirty = (itemId: number, dirty: boolean) => void;

function ItemCard({
  item,
  batchId,
  editable,
  onDirty,
}: {
  item: Item;
  batchId: number;
  editable: boolean;
  onDirty: OnDirty;
}) {
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: (patch: ItemPatch) => patchItem(item.id, patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["batch", batchId] }),
  });
  const skipped = item.status === "skipped";
  const border = item.needs_input.length
    ? "border-amber-400"
    : item.match_status === "conflict"
      ? "border-red-400"
      : "border-gray-200";

  return (
    <article className={`rounded-lg border-2 p-3 text-sm ${border} ${skipped ? "opacity-50" : ""}`}>
      {item.kind === "cash" ? <CashBody item={item} /> : <LotBody item={item} />}

      {item.diff.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-gray-800">
          {item.diff.map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>
      )}
      {item.warnings.map((w) => (
        <p key={w} className="mt-1 text-amber-800">
          ⚠ {w}
        </p>
      ))}
      {item.needs_input.length > 0 && !skipped && (
        <p className="mt-2 font-medium text-amber-800">Needs: {item.needs_input.join(", ")}</p>
      )}

      {editable && item.status !== "committed" && (
        <>
          {!skipped &&
            (item.kind === "cash" ? (
              <CashForm item={item} onSave={save.mutate} onDirty={onDirty} />
            ) : (
              <LotForm item={item} onSave={save.mutate} onDirty={onDirty} />
            ))}
          <button
            className="mt-2 text-xs text-gray-600 underline"
            onClick={() => save.mutate({ status: skipped ? "pending" : "skipped" })}
          >
            {skipped ? "Include this item" : "Skip this item"}
          </button>
          {save.error && <p className="mt-1 text-red-700">{save.error.message}</p>}
        </>
      )}
    </article>
  );
}

function LotBody({ item }: { item: Item }) {
  const p = item.payload;
  const buys = p.buys ?? [];
  const qty = buys.reduce((n, b) => n + b.qty, 0);
  const cost = buys.reduce((n, b) => n + b.qty * Number(b.price), 0); // display only
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{item.symbol ?? p.symbol}</span>
        <span className="text-gray-500">{p.strategy === "momentum" ? "momentum · Zerodha" : "long-term · Groww"}</span>
        <Badge text={item.match_status} />
        {item.status !== "pending" && <span className="text-xs text-gray-500">{item.status}</span>}
      </div>
      <div className="mt-1 text-gray-700">
        Bought {qty} @ {inr(String(cost / qty))} on {p.opened_on ?? "?"} · {item.open_qty ?? "?"} open
        {p.stop && <> · stop {inr(p.stop)}</>}
      </div>
      {(p.exits ?? []).map((e, n) => (
        <div key={n} className="flex items-center gap-2 text-gray-700">
          <span>
            {e.label ?? "Sold"} {e.qty} @ {inr(e.price)} on {e.date}
          </span>
          {item.outcomes[n] && <Badge text={item.outcomes[n]} />}
        </div>
      ))}
      {!!p.targets?.length && (
        <div className="text-gray-700">Planned: {p.targets.map((t) => `${t.label} ${inr(t.price)}`).join(", ")}</div>
      )}
      {!!p.exits?.length && <div className="text-gray-700">Realised {inr(item.realised)} gross</div>}
      {p.remarks && <div className="text-gray-500 italic">“{p.remarks}”</div>}
      {p.strategy === "long_term" && !p.thesis && <div className="text-gray-500">No thesis yet</div>}
    </>
  );
}

function CashBody({ item }: { item: Item }) {
  const p = item.payload;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="font-semibold">Cash · {p.account}</span>
      {p.amount != null ? (
        <span>
          {inr(p.amount)} on {p.as_of ?? "?"}
        </span>
      ) : (
        <span className="text-gray-500">optional: left empty, it isn't committed</span>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col text-xs text-gray-600">
      {label}
      {children}
    </label>
  );
}

const input = "rounded border p-1.5 text-sm text-gray-900";

/** Tell the batch whether this form holds unsaved values; clears itself when the form goes away. */
function useReportDirty(itemId: number, dirty: boolean, onDirty: OnDirty) {
  useEffect(() => {
    onDirty(itemId, dirty);
    return () => onDirty(itemId, false);
  }, [itemId, dirty, onDirty]);
}

const same = (a: string | null | undefined, b: string | null | undefined) =>
  (a ?? "") === (b ?? "") || (a != null && b != null && a !== "" && b !== "" && Number(a) === Number(b));

function LotForm({ item, onSave, onDirty }: { item: Item; onSave: (patch: ItemPatch) => void; onDirty: OnDirty }) {
  const p = item.payload;
  const planned = (label: string) => p.targets?.find((t) => t.label === label)?.price ?? "";
  const [form, setForm] = useState({
    opened_on: p.opened_on ?? "",
    stop: p.stop ?? "",
    T1: planned("T1"),
    T2: planned("T2"),
    thesis: p.thesis ?? "",
    review_trigger: p.review_trigger ?? "",
  });
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [key]: e.target.value });
  const dirty =
    !same(form.opened_on, p.opened_on) ||
    !same(form.stop, p.stop) ||
    !same(form.T1, planned("T1")) ||
    !same(form.T2, planned("T2")) ||
    form.thesis !== (p.thesis ?? "") ||
    form.review_trigger !== (p.review_trigger ?? "");
  useReportDirty(item.id, dirty, onDirty);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const targets: Target[] = (p.targets ?? []).filter((t) => t.label !== "T1" && t.label !== "T2");
    for (const label of ["T1", "T2"] as const) if (form[label]) targets.push({ label, price: form[label] });
    targets.sort((a, b) => a.label.localeCompare(b.label));
    const patch: ItemPatch = { targets, stop: form.stop || null };
    if (form.opened_on) patch.opened_on = form.opened_on;
    if (p.strategy === "long_term") {
      patch.thesis = form.thesis || null;
      patch.review_trigger = form.review_trigger || null;
    }
    onSave(patch);
  };

  const momentum = p.strategy === "momentum";
  const open = (item.open_qty ?? 0) > 0;
  if (!open && !item.needs_input.includes("opened_on")) return null; // closed trades: nothing to plan
  return (
    <form onSubmit={submit} className="mt-2 grid grid-cols-2 gap-2">
      {(item.needs_input.includes("opened_on") || !p.opened_on) && (
        <Field label="Bought on">
          <input type="date" className={input} value={form.opened_on} onChange={set("opened_on")} />
        </Field>
      )}
      {momentum && open && (
        <>
          <Field label="Stop (GTT trigger)">
            <input inputMode="decimal" className={input} value={form.stop} onChange={set("stop")} />
          </Field>
          <Field label="T1">
            <input inputMode="decimal" className={input} value={form.T1} onChange={set("T1")} />
          </Field>
          <Field label="T2">
            <input inputMode="decimal" className={input} value={form.T2} onChange={set("T2")} />
          </Field>
        </>
      )}
      {!momentum && open && (
        <>
          <Field label="Thesis">
            <input className={input} value={form.thesis} onChange={set("thesis")} />
          </Field>
          <Field label="Review trigger">
            <input className={input} value={form.review_trigger} onChange={set("review_trigger")} />
          </Field>
        </>
      )}
      <button className="col-span-2 rounded bg-gray-200 py-1.5 font-medium">Save</button>
    </form>
  );
}

function CashForm({ item, onSave, onDirty }: { item: Item; onSave: (patch: ItemPatch) => void; onDirty: OnDirty }) {
  const [amount, setAmount] = useState(item.payload.amount ?? "");
  const [asOf, setAsOf] = useState(item.payload.as_of ?? new Date().toISOString().slice(0, 10));
  // The date alone isn't an edit: it is pre-filled with today.
  useReportDirty(item.id, !same(amount, item.payload.amount) || (amount !== "" && asOf !== item.payload.as_of), onDirty);
  return (
    <form
      className="mt-2 grid grid-cols-2 gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        onSave({ amount: amount || null, as_of: asOf || null });
      }}
    >
      <Field label="Unutilised funds (₹)">
        <input inputMode="decimal" className={input} value={amount} onChange={(e) => setAmount(e.target.value)} />
      </Field>
      <Field label="As of">
        <input type="date" className={input} value={asOf} onChange={(e) => setAsOf(e.target.value)} />
      </Field>
      <button className="col-span-2 rounded bg-gray-200 py-1.5 font-medium">Save</button>
    </form>
  );
}
