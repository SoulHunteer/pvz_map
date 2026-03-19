import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { EmptyState } from "../components/EmptyState";
import { StatusBadge } from "../components/StatusBadge";
import { api } from "../lib/api";
import { formatDateTime, truncateLink } from "../lib/format";
import { useSession } from "../lib/session";
import { TrackedItem } from "../lib/types";

export function TrackedItemsPage(): JSX.Element {
  const { auth, refreshMe } = useSession();
  const [items, setItems] = useState<TrackedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadItems = async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await api.listTrackedItems(auth);
      setItems(rows);
      await refreshMe();
    } catch (loadError) {
      const msg = loadError instanceof Error ? loadError.message : "Failed to load tracked items";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadItems();
  }, [auth.telegramId]);

  const checkNow = async (trackedItemId: number) => {
    setBusyId(trackedItemId);
    setMessage(null);
    setError(null);
    try {
      const result = await api.runManualCheck(auth, trackedItemId);
      setMessage(
        `Check completed: status=${result.status}, zones=${result.zone_count}, added=${result.added_count}, removed=${result.removed_count}`
      );
      await loadItems();
    } catch (runError) {
      const msg = runError instanceof Error ? runError.message : "Manual check failed";
      setError(msg);
    } finally {
      setBusyId(null);
    }
  };

  const toggleItem = async (item: TrackedItem) => {
    setBusyId(item.id);
    setMessage(null);
    setError(null);
    try {
      await api.patchTrackedItem(auth, item.id, { is_active: !item.is_active });
      setMessage(item.is_active ? "Monitoring paused" : "Monitoring enabled");
      await loadItems();
    } catch (toggleError) {
      const msg = toggleError instanceof Error ? toggleError.message : "Failed to update status";
      setError(msg);
    } finally {
      setBusyId(null);
    }
  };

  const deleteItem = async (item: TrackedItem) => {
    const confirmed = window.confirm(`Delete tracking \"${item.title}\"?`);
    if (!confirmed) {
      return;
    }

    setBusyId(item.id);
    setMessage(null);
    setError(null);
    try {
      await api.deleteTrackedItem(auth, item.id);
      setMessage("Tracking deleted");
      await loadItems();
    } catch (deleteError) {
      const msg = deleteError instanceof Error ? deleteError.message : "Failed to delete tracking";
      setError(msg);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="panel section-stack">
      <div className="section-head">
        <h2>My trackings</h2>
        <Link to="/tracked-items/new" className="btn btn-primary">
          Add tracking
        </Link>
      </div>

      {message && <p className="success-text">{message}</p>}
      {error && <p className="error-text">{error}</p>}

      {loading ? (
        <p>Loading tracked items...</p>
      ) : items.length === 0 ? (
        <EmptyState title="No active records" description="Create your first tracking to start monitoring." />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th>Status</th>
                <th>Map link</th>
                <th>Zones</th>
                <th>Last check</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>{item.title}</td>
                  <td>
                    <StatusBadge status={item.last_status} />
                  </td>
                  <td title={item.map_link}>{truncateLink(item.map_link)}</td>
                  <td>{item.last_zone_count}</td>
                  <td>{formatDateTime(item.last_success_at || item.last_check_at)}</td>
                  <td>
                    <div className="actions-row">
                      <button className="btn btn-ghost" onClick={() => void checkNow(item.id)} disabled={busyId === item.id}>
                        Check now
                      </button>
                      <button className="btn btn-ghost" onClick={() => void toggleItem(item)} disabled={busyId === item.id}>
                        {item.is_active ? "Pause" : "Enable"}
                      </button>
                      <Link className="btn btn-ghost" to={`/tracked-items/${item.id}/photo`}>
                        Просмотреть фото проверки
                      </Link>
                      <Link className="btn btn-ghost" to={`/tracked-items/${item.id}`}>Редактировать</Link>
                      <button className="btn btn-danger" onClick={() => void deleteItem(item)} disabled={busyId === item.id}>
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

