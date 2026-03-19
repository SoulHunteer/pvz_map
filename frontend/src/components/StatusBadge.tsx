interface StatusBadgeProps {
  status: string;
}

export function StatusBadge({ status }: StatusBadgeProps): JSX.Element {
  const normalized = status.toLowerCase();
  const cssClass =
    normalized === "success"
      ? "badge badge-success"
      : normalized === "error"
        ? "badge badge-error"
        : normalized === "empty"
          ? "badge badge-empty"
          : "badge";

  return <span className={cssClass}>{status}</span>;
}
