import { useQuery } from "@tanstack/react-query";

type Health = { status: "ok" | "degraded"; db: string };

async function fetchHealth(): Promise<Health> {
  const res = await fetch("/api/health");
  // 503 still carries a Health body; anything else (API down, proxy error) is a real failure.
  if (res.status !== 200 && res.status !== 503) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export default function Health() {
  const { data, error, isPending } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 10_000,
    retry: false,
  });

  const ok = data?.status === "ok";
  const text = isPending
    ? "Checking…"
    : error
      ? `API unreachable (${error.message})`
      : `API: ok · DB: ${data!.db}`;

  return (
    <section>
      <h2 className="mb-3 font-semibold">Health</h2>
      <div
        role="status"
        className={`rounded-lg border p-4 ${
          isPending
            ? "border-gray-300 bg-gray-50"
            : ok
              ? "border-green-300 bg-green-50 text-green-900"
              : "border-red-300 bg-red-50 text-red-900"
        }`}
      >
        {text}
      </div>
    </section>
  );
}
