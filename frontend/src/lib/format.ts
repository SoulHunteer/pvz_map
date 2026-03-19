export function formatDateTime(value?: string | null): string {
  if (!value) {
    return "-";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("ru-RU", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

export function truncateLink(link: string, max = 56): string {
  if (link.length <= max) {
    return link;
  }
  return `${link.slice(0, max - 1)}...`;
}

export function toPercent(current: number, total: number): number {
  if (total <= 0) {
    return 0;
  }
  return Math.min(100, Math.round((current / total) * 100));
}
