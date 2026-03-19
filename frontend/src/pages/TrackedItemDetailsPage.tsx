import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { EmptyState } from "../components/EmptyState";
import { StatusBadge } from "../components/StatusBadge";
import { api, resolveArtifactUrl } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { useSession } from "../lib/session";
import { TrackedItemDetails } from "../lib/types";

export function TrackedItemDetailsPage(): JSX.Element {
  const navigate = useNavigate();
  const { id } = useParams();
  const trackedItemId = Number(id);
  const { auth, refreshMe } = useSession();

  const [details, setDetails] = useState<TrackedItemDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [savingEdit, setSavingEdit] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [editTitle, setEditTitle] = useState("");
  const [editMapLink, setEditMapLink] = useState("");

  const load = async () => {
    if (!Number.isFinite(trackedItemId)) {
      setLoadError("Invalid tracked item ID");
      setLoading(false);
      return;
    }

    setLoading(true);
    setLoadError(null);
    try {
      const payload = await api.getTrackedItem(auth, trackedItemId);
      setDetails(payload);
      setEditTitle(payload.item.title);
      setEditMapLink(payload.item.map_link);
      await refreshMe();
    } catch (error) {
      const text = error instanceof Error ? error.message : "Failed to load item details";
      setLoadError(text);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [trackedItemId, auth.telegramId]);

  const lastSnapshot = useMemo(() => details?.snapshots[0] || null, [details]);
  const processedImageUrl = resolveArtifactUrl(lastSnapshot?.processed_image_path);
  const diffImageUrl = resolveArtifactUrl(lastSnapshot?.diff_image_path);

  const hasEditChanges = details
    ? editTitle.trim() !== details.item.title || editMapLink.trim() !== details.item.map_link
    : false;

  const runCheck = async () => {
    setBusy(true);
    setMessage(null);
    setActionError(null);
    try {
      const result = await api.runManualCheck(auth, trackedItemId);
      setMessage(
        `Check done: status=${result.status}, zones=${result.zone_count}, added=${result.added_count}, removed=${result.removed_count}`
      );
      await load();
    } catch (error) {
      const text = error instanceof Error ? error.message : "Manual check failed";
      setActionError(text);
    } finally {
      setBusy(false);
    }
  };

  const saveItemChanges = async () => {
    if (!details) {
      return;
    }

    const nextTitle = editTitle.trim();
    const nextMapLink = editMapLink.trim();

    if (!nextTitle) {
      setActionError("Название отслеживания не может быть пустым");
      return;
    }

    if (!nextMapLink) {
      setActionError("Ссылка отслеживания не может быть пустой");
      return;
    }

    setSavingEdit(true);
    setMessage(null);
    setActionError(null);
    try {
      await api.patchTrackedItem(auth, trackedItemId, {
        title: nextTitle,
        map_link: nextMapLink
      });
      setMessage("Параметры отслеживания обновлены");
      await load();
    } catch (error) {
      const text = error instanceof Error ? error.message : "Не удалось обновить отслеживание";
      setActionError(text);
    } finally {
      setSavingEdit(false);
    }
  };

  const resetItemChanges = () => {
    if (!details) {
      return;
    }
    setEditTitle(details.item.title);
    setEditMapLink(details.item.map_link);
    setActionError(null);
  };

  const toggleActive = async () => {
    if (!details) {
      return;
    }

    setBusy(true);
    setMessage(null);
    setActionError(null);
    try {
      await api.patchTrackedItem(auth, trackedItemId, { is_active: !details.item.is_active });
      setMessage(details.item.is_active ? "Monitoring paused" : "Monitoring enabled");
      await load();
    } catch (error) {
      const text = error instanceof Error ? error.message : "Failed to update status";
      setActionError(text);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!details) {
      return;
    }

    if (!window.confirm(`Delete tracking \"${details.item.title}\"?`)) {
      return;
    }

    setBusy(true);
    setActionError(null);
    try {
      await api.deleteTrackedItem(auth, trackedItemId);
      await refreshMe();
      navigate("/tracked-items");
    } catch (error) {
      const text = error instanceof Error ? error.message : "Failed to delete item";
      setActionError(text);
      setBusy(false);
    }
  };

  if (loading) {
    return <section className="panel">Loading details...</section>;
  }

  if (loadError) {
    return <section className="panel error-text">{loadError}</section>;
  }

  if (!details) {
    return <EmptyState title="Item not found" description="Tracked item is not available for this user." />;
  }

  return (
    <>
      <section className="panel section-stack">
        <div className="section-head">
          <div>
            <p className="eyebrow">Tracked item #{details.item.id}</p>
            <h2>{details.item.title}</h2>
          </div>
          <Link className="btn btn-ghost" to="/tracked-items">
            Back
          </Link>
        </div>

        <div className="meta-grid">
          <article>
            <p className="meta-label">Current status</p>
            <StatusBadge status={details.item.last_status} />
          </article>
          <article>
            <p className="meta-label">Zones</p>
            <p>{details.item.last_zone_count}</p>
          </article>
          <article>
            <p className="meta-label">Last success</p>
            <p>{formatDateTime(details.item.last_success_at)}</p>
          </article>
          <article>
            <p className="meta-label">Monitoring</p>
            <p>{details.item.is_active ? "active" : "paused"}</p>
          </article>
        </div>

        <form
          className="form"
          onSubmit={(event) => {
            event.preventDefault();
            void saveItemChanges();
          }}
        >
          <h3>Редактирование отслеживания</h3>

          <label>
            Название отслеживания
            <input
              type="text"
              value={editTitle}
              onChange={(event) => setEditTitle(event.target.value)}
              disabled={busy || savingEdit}
            />
          </label>

          <label>
            Ссылка карты
            <input
              type="url"
              value={editMapLink}
              onChange={(event) => setEditMapLink(event.target.value)}
              disabled={busy || savingEdit}
            />
          </label>

          <div className="actions-row">
            <button className="btn btn-primary" type="submit" disabled={!hasEditChanges || busy || savingEdit}>
              {savingEdit ? "Сохраняю..." : "Сохранить изменения"}
            </button>
            <button className="btn btn-ghost" type="button" onClick={resetItemChanges} disabled={!hasEditChanges || busy || savingEdit}>
              Сбросить
            </button>
          </div>
        </form>

        <div className="actions-row">
          <button className="btn btn-primary" onClick={() => void runCheck()} disabled={busy || savingEdit}>
            Check now
          </button>
          <button className="btn btn-ghost" onClick={() => void toggleActive()} disabled={busy || savingEdit}>
            {details.item.is_active ? "Pause monitoring" : "Enable monitoring"}
          </button>
          <Link className="btn btn-ghost" to={`/tracked-items/${details.item.id}/photo`}>
            Просмотреть фото проверки
          </Link>
          <button className="btn btn-danger" onClick={() => void remove()} disabled={busy || savingEdit}>
            Delete
          </button>
        </div>

        {message && <p className="success-text">{message}</p>}
        {actionError && <p className="error-text">{actionError}</p>}
      </section>

      <section className="panel section-stack">
        <h3>Latest processed image</h3>
        {processedImageUrl ? (
          <img src={processedImageUrl} alt="Processed zones" className="preview-image preview-image-capped" />
        ) : (
          <p className="muted">No processed image yet.</p>
        )}
      </section>

      <section className="panel section-stack">
        <h3>Latest diff image</h3>
        {diffImageUrl ? <img src={diffImageUrl} alt="Diff zones" className="preview-image preview-image-capped" /> : <p className="muted">No diff image yet.</p>}
      </section>

      <section className="panel section-stack">
        <h3>Recent snapshots</h3>
        {details.snapshots.length === 0 ? (
          <p className="muted">No snapshots yet.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Checked at</th>
                  <th>Status</th>
                  <th>Zones</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {details.snapshots.map((snapshot) => (
                  <tr key={snapshot.id}>
                    <td>{snapshot.id}</td>
                    <td>{formatDateTime(snapshot.checked_at)}</td>
                    <td>
                      <StatusBadge status={snapshot.status} />
                    </td>
                    <td>{snapshot.zone_count}</td>
                    <td>{snapshot.error_message || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel section-stack">
        <h3>Recent events</h3>
        {details.events.length === 0 ? (
          <p className="muted">No events yet.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Type</th>
                  <th>Added</th>
                  <th>Removed</th>
                </tr>
              </thead>
              <tbody>
                {details.events.map((event) => (
                  <tr key={event.id}>
                    <td>{formatDateTime(event.created_at)}</td>
                    <td>{event.event_type}</td>
                    <td>{event.added_count}</td>
                    <td>{event.removed_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

