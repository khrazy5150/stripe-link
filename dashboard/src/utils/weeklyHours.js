export const DAYS = [
  { key: "mon", label: "Mon" },
  { key: "tue", label: "Tue" },
  { key: "wed", label: "Wed" },
  { key: "thu", label: "Thu" },
  { key: "fri", label: "Fri" },
  { key: "sat", label: "Sat" },
  { key: "sun", label: "Sun" },
];

// Mon–Fri 8–6, weekend off — the shape both Fulfiller.availability.weekly_hours and
// TenantAvailability.weekly_hours expect (7 ordered day objects).
export function defaultWeeklyHours() {
  return DAYS.map(({ key }) => ({
    day: key,
    enabled: key !== "sat" && key !== "sun",
    start_time: "08:00",
    end_time: "18:00",
  }));
}

// Coerce any stored value into 7 ordered days, filling gaps — so the widget never breaks
// on a partial/legacy document.
export function normalizeWeeklyHours(value) {
  const byDay = new Map((Array.isArray(value) ? value : []).map((d) => [d?.day, d]));
  return DAYS.map(({ key }) => {
    const d = byDay.get(key) || {};
    return {
      day: key,
      enabled: Boolean(d.enabled),
      start_time: d.start_time || "08:00",
      end_time: d.end_time || "18:00",
    };
  });
}

export function dayLabel(day) {
  return DAYS.find((d) => d.key === day)?.label || day;
}
