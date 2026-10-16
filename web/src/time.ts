// <input type="datetime-local"> values in Riyadh time (UTC+3, no daylight saving).
const RIYADH_MS = 3 * 3600 * 1000;

// "2026-10-18T03:00:00Z" -> "2026-10-18T06:00"
export const toRiyadhInput = (iso: string) => new Date(new Date(iso).getTime() + RIYADH_MS).toISOString().slice(0, 16);

// "2026-10-18T06:00" -> "2026-10-18T06:00:00+03:00"
export const fromRiyadhInput = (value: string) => `${value}:00+03:00`;

export const addHours = (iso: string, hours: number) => new Date(new Date(iso).getTime() + hours * 3600000).toISOString();
