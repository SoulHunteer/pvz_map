interface EmptyStateProps {
  title: string;
  description: string;
}

export function EmptyState({ title, description }: EmptyStateProps): JSX.Element {
  return (
    <section className="panel empty-state">
      <h3>{title}</h3>
      <p className="muted">{description}</p>
    </section>
  );
}
