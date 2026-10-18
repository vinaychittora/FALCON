export function captureDate(value: string | null | undefined) {
  if (!value || !/(?:Z|[+-]\d{2}:\d{2})$/i.test(value)) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function captureTime(value: string | null | undefined) {
  const date = captureDate(value);
  if (!date) return null;
  return {
    date: date.toLocaleDateString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric",
    }),
    time: date.toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      timeZoneName: "short",
      hour12: false,
    }),
    utc: date.toISOString(),
  };
}
