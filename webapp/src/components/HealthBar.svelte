<script lang="ts">
  // Overview health bar (UI-REDESIGN-2026-11 (1) + decision ~10:20Z): money path
  // first — trader VM, IB gateway, phone app — then trainer VM, Kaggle, Hugging Face.
  // A component with no source the SPA can read says "could not look" in grey:
  // never green by default (manager, 2026-11-12).
  //
  // Sources (all ungated):
  //   trader VM  — /api/bot/health/latest (the VM's own deterministic health
  //                snapshot) + /api/bot/health/services (ict-trader-live active)
  //   phone app  — /api/bot/prop/phone_steps: the newest run's last_at = last seen
  //   IB gateway, trainer VM, Kaggle, Hugging Face — no SPA-readable route yet
  //                (the gateway VM is isolated; the trainer/infra reads live on the
  //                console connector behind its own sign-in).
  import { onMount, onDestroy } from "svelte";
  import { api } from "../lib/api";
  import { agoFromIso } from "../lib/format";

  type Light = "ok" | "warn" | "bad" | "unknown";
  type Chip = { name: string; light: Light; text: string; title: string };

  const SNAPSHOT_STALE_MIN = 15; // the health snapshot timer runs every few minutes
  const PHONE_OK_MIN = 30, PHONE_WARN_MIN = 6 * 60;

  let trader = $state<Chip>({ name: "Trader VM", light: "unknown", text: "loading", title: "" });
  let phone = $state<Chip>({ name: "Phone app", light: "unknown", text: "loading", title: "" });
  const noSource = (name: string, why: string): Chip => ({ name, light: "unknown", text: "could not look", title: why });
  const chips = $derived<Chip[]>([
    trader,
    noSource("IB gateway", "No dashboard route reads the IB gateway VM (it is isolated); the bot's health snapshot carries no gateway check."),
    phone,
    noSource("Trainer VM", "No dashboard-readable trainer health route yet (the console reads it behind its own sign-in)."),
    noSource("Kaggle", "No route reports Kaggle (off-system training) status yet."),
    noSource("Hugging Face", "No route reports Hugging Face status yet."),
  ]);

  const minsSince = (iso: string | null | undefined): number | null => {
    const ms = iso ? Date.parse(iso) : NaN;
    return Number.isNaN(ms) ? null : (Date.now() - ms) / 60000;
  };

  async function loadTrader() {
    const [h, s] = await Promise.allSettled([api.healthLatest(), api.healthServices()]);
    const snap = h.status === "fulfilled" ? h.value?.snapshot : null;
    const svc = s.status === "fulfilled" ? (s.value?.services ?? []).find((x: any) => x?.unit === "ict-trader-live.service") : null;
    if (!snap && !svc) {
      trader = { name: "Trader VM", light: "unknown", text: "could not look", title: "Neither /health/latest nor /health/services answered." };
      return;
    }
    const age = minsSince(snap?.timestamp);
    const status = String(snap?.status ?? "").toLowerCase();
    const svcUp = svc ? svc.state === "active" : null;
    let light: Light = "ok";
    if (svcUp === false || (status && status !== "ok")) light = "bad";
    else if (!snap || age == null || age > SNAPSHOT_STALE_MIN) light = "warn";
    const text = svcUp === false ? `trader ${svc.state}` : !snap ? "snapshot missing" : age != null && age > SNAPSHOT_STALE_MIN ? `snapshot ${agoFromIso(snap.timestamp)}` : (status || "—");
    trader = { name: "Trader VM", light, text, title: [snap?.summary, svc ? `ict-trader-live: ${svc.state}/${svc.sub_state}` : null, snap?.timestamp ? `snapshot ${snap.timestamp}` : null].filter(Boolean).join("\n") };
  }

  async function loadPhone() {
    try {
      const r = await api.phoneSteps();
      const last = ((r?.runs ?? []) as any[]).map((x) => x?.last_at).filter(Boolean).sort().pop() ?? null;
      const m = minsSince(last);
      if (m == null) { phone = { name: "Phone app", light: "unknown", text: "no runs recorded", title: "No phone step runs in the retention window." }; return; }
      phone = {
        name: "Phone app", light: m <= PHONE_OK_MIN ? "ok" : m <= PHONE_WARN_MIN ? "warn" : "bad",
        text: `seen ${agoFromIso(last)}`,
        title: `Last phone step ${last} (green ≤ ${PHONE_OK_MIN} min, amber ≤ ${PHONE_WARN_MIN / 60} h). Last-seen only: the phone runs when a prop ticket needs it, so a quiet market reads amber/red without a fault.`,
      };
    } catch (e) {
      phone = { name: "Phone app", light: "unknown", text: "could not look", title: e instanceof Error ? e.message : String(e) };
    }
  }

  let timer: ReturnType<typeof setInterval> | null = null;
  const load = () => { loadTrader(); loadPhone(); };
  onMount(() => { load(); timer = setInterval(() => { if (!document.hidden) load(); }, 60000); });
  onDestroy(() => { if (timer) clearInterval(timer); });
</script>

<div class="hbar panel" role="status" aria-label="System health">
  {#each chips as c (c.name)}
    <span class="chip {c.light}" title={c.title}>
      <span class="dot" aria-hidden="true"></span><b>{c.name}</b> <span class="t">{c.text}</span>
    </span>
  {/each}
</div>

<style>
  .hbar { display: flex; flex-wrap: wrap; gap: 6px; padding: 8px 10px; }
  .chip { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; padding: 3px 9px; border-radius: 999px; border: 1px solid var(--border); background: var(--panel-2); white-space: nowrap; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); flex: none; }
  .ok .dot { background: var(--pos); }
  .warn .dot { background: #d4a017; }
  .bad .dot { background: var(--neg); }
  .bad { border-color: var(--neg); }
  .unknown { color: var(--muted); }
  .t { color: var(--muted); }
</style>
