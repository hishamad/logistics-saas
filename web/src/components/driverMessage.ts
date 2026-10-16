// A truck's plan as a short message a dispatcher can paste into WhatsApp.
import type { Board, BoardTeam } from "../api";

type Words = { header: string; load: string; unload: string; none: string };

export function driverMessage(
  board: Board,
  team: BoardTeam,
  words: Words,
  when: (minute: number) => string,
  site: (id: string) => string,
): string {
  const lines = [words.header];
  const seen = new Set<string>();
  for (const act of team.acts) {
    const jobId = act[3];
    if (!jobId || seen.has(jobId)) continue;
    seen.add(jobId);
    const job = board.jobs[jobId];
    const loading = team.acts.find((a) => a[3] === jobId && a[8] === "loading");
    const unloading = team.acts.find((a) => a[3] === jobId && a[8] === "unloading");
    lines.push("", `${seen.size}. ${job.ref} · ${job.customer}`);
    if (loading) lines.push(`   ${words.load}: ${when(loading[1])} – ${site(loading[4])}`);
    if (unloading) lines.push(`   ${words.unload}: ${when(unloading[1])} – ${site(unloading[4])}`);
  }
  if (seen.size === 0) lines.push(words.none);
  return lines.join("\n");
}
