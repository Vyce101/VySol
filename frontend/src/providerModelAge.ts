export function providerModelAge(timestamp: string, now = Date.now()) {
  const updatedAt = Date.parse(timestamp);
  if (!Number.isFinite(updatedAt)) return "at an unknown time";

  const elapsedMinutes = Math.max(0, Math.floor((now - updatedAt) / 60_000));
  if (elapsedMinutes === 0) return "just now";
  if (elapsedMinutes < 60) return `${elapsedMinutes} minute${elapsedMinutes === 1 ? "" : "s"} ago`;

  const elapsedHours = Math.floor(elapsedMinutes / 60);
  if (elapsedHours < 24) return `${elapsedHours} hour${elapsedHours === 1 ? "" : "s"} ago`;

  const elapsedDays = Math.floor(elapsedHours / 24);
  return `${elapsedDays} day${elapsedDays === 1 ? "" : "s"} ago`;
}
