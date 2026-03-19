import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { useSession } from "../lib/session";
import { CreateTrackedItemResponse } from "../lib/types";

export function CreateTrackedItemPage(): JSX.Element {
  const navigate = useNavigate();
  const { auth, refreshMe } = useSession();
  const [title, setTitle] = useState("");
  const [mapLink, setMapLink] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [runInitialCheck, setRunInitialCheck] = useState(true);
  const [result, setResult] = useState<CreateTrackedItemResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setResult(null);

    try {
      const payload = await api.createTrackedItem(auth, {
        title: title.trim() || undefined,
        map_link: mapLink.trim(),
        is_active: isActive,
        run_initial_check: runInitialCheck
      });

      setResult(payload);
      await refreshMe();
    } catch (submitError) {
      const message = submitError instanceof Error ? submitError.message : "Failed to create tracking";
      setError(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="panel section-stack">
      <div className="section-head">
        <h2>Create tracking</h2>
        <Link className="btn btn-ghost" to="/tracked-items">
          Back to list
        </Link>
      </div>

      <form className="form" onSubmit={onSubmit}>
        <label>
          Title
          <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Moscow South-East" />
        </label>

        <label>
          Map link
          <input
            required
            type="url"
            value={mapLink}
            onChange={(event) => setMapLink(event.target.value)}
            placeholder="https://map.wb.ru/..."
          />
        </label>

        <label className="checkbox-row">
          <input type="checkbox" checked={isActive} onChange={(event) => setIsActive(event.target.checked)} />
          Enable monitoring after creation
        </label>

        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={runInitialCheck}
            onChange={(event) => setRunInitialCheck(event.target.checked)}
          />
          Run initial check immediately
        </label>

        <button type="submit" className="btn btn-primary" disabled={submitting}>
          {submitting ? "Creating..." : "Create tracking"}
        </button>
      </form>

      {error && <p className="error-text">{error}</p>}

      {result && (
        <section className="result-block">
          <h3>Tracking created</h3>
          <p>ID: {result.item.id}</p>
          <p>Title: {result.item.title}</p>
          <p>Status: {result.item.last_status}</p>
          {result.initial_check ? (
            <>
              <p>Initial check: {result.initial_check.status}</p>
              <p>Checked at: {formatDateTime(result.initial_check.checked_at)}</p>
              <p>Zones: {result.initial_check.zone_count}</p>
              {result.initial_check.error_message && <p className="error-text">{result.initial_check.error_message}</p>}
            </>
          ) : (
            <p className="muted">Initial check was skipped.</p>
          )}
          <div className="actions-row">
            <button className="btn btn-primary" onClick={() => navigate(`/tracked-items/${result.item.id}`)}>
              Open details
            </button>
            <button className="btn btn-ghost" onClick={() => navigate("/tracked-items")}>Go to trackings</button>
          </div>
        </section>
      )}
    </section>
  );
}
