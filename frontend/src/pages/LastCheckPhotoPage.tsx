import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { EmptyState } from "../components/EmptyState";
import { StatusBadge } from "../components/StatusBadge";
import { api, resolveArtifactUrl } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { useSession } from "../lib/session";
import { SnapshotZoneDiff, SnapshotZoneOverlay, TrackedItemDetails } from "../lib/types";

function zoneColor(status: SnapshotZoneOverlay["status"]): string {
  if (status === "added") {
    return "#34c759";
  }
  if (status === "removed") {
    return "#eb5757";
  }
  return "#56ccf2";
}

function zoneStatusText(status: SnapshotZoneOverlay["status"]): string {
  if (status === "added") {
    return "Новая зона";
  }
  if (status === "removed") {
    return "Удалена";
  }
  return "Стабильная";
}

function chipClass(active: boolean): string {
  return active ? "filter-chip filter-chip-active" : "filter-chip";
}

export function LastCheckPhotoPage(): JSX.Element {
  const { id } = useParams();
  const trackedItemId = Number(id);
  const { auth } = useSession();

  const [details, setDetails] = useState<TrackedItemDetails | null>(null);
  const [zoneDiff, setZoneDiff] = useState<SnapshotZoneDiff | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [zoneError, setZoneError] = useState<string | null>(null);

  const [showAdded, setShowAdded] = useState(true);
  const [showRemoved, setShowRemoved] = useState(true);
  const [showStable, setShowStable] = useState(true);
  const [hoveredZone, setHoveredZone] = useState<SnapshotZoneOverlay | null>(null);

  const [imageSize, setImageSize] = useState<{ width: number; height: number } | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      if (!Number.isFinite(trackedItemId)) {
        setError("Некорректный ID отслеживания");
        setLoading(false);
        return;
      }

      setLoading(true);
      setError(null);
      try {
        const payload = await api.getTrackedItem(auth, trackedItemId);
        if (!cancelled) {
          setDetails(payload);
        }
      } catch (loadError) {
        if (!cancelled) {
          const message = loadError instanceof Error ? loadError.message : "Не удалось загрузить последнюю проверку";
          setError(message);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [auth, trackedItemId]);

  const latestSnapshot = useMemo(() => details?.snapshots[0] || null, [details]);

  useEffect(() => {
    let cancelled = false;

    const loadZoneDiff = async () => {
      if (!latestSnapshot) {
        setZoneDiff(null);
        setZoneError(null);
        return;
      }

      try {
        const payload = await api.getSnapshotZoneDiff(auth, trackedItemId, latestSnapshot.id);
        if (!cancelled) {
          setZoneDiff(payload);
          setZoneError(null);
        }
      } catch (loadError) {
        if (!cancelled) {
          const message = loadError instanceof Error ? loadError.message : "Не удалось загрузить интерактивную разметку зон";
          setZoneError(message);
          setZoneDiff(null);
        }
      }
    };

    void loadZoneDiff();
    return () => {
      cancelled = true;
    };
  }, [auth, trackedItemId, latestSnapshot?.id]);

  useEffect(() => {
    setHoveredZone(null);
  }, [latestSnapshot?.id]);

  const screenshotUrl = resolveArtifactUrl(latestSnapshot?.screenshot_path);
  const processedUrl = resolveArtifactUrl(latestSnapshot?.processed_image_path);
  const diffUrl = resolveArtifactUrl(latestSnapshot?.diff_image_path);

  const visibleZones = useMemo(() => {
    if (!zoneDiff) {
      return [];
    }

    return zoneDiff.zones.filter((zone) => {
      if (zone.status === "added") {
        return showAdded;
      }
      if (zone.status === "removed") {
        return showRemoved;
      }
      return showStable;
    });
  }, [zoneDiff, showAdded, showRemoved, showStable]);

  if (loading) {
    return <section className="panel">Загружаю последнюю проверку...</section>;
  }

  if (error) {
    return <section className="panel error-text">{error}</section>;
  }

  if (!details) {
    return <EmptyState title="Нет данных" description="Отслеживание не найдено." />;
  }

  if (!latestSnapshot) {
    return (
      <section className="panel section-stack">
        <div className="section-head">
          <h2>Последняя проверка: {details.item.title}</h2>
          <Link className="btn btn-ghost" to={`/tracked-items/${details.item.id}`}>
            К деталям
          </Link>
        </div>
        <EmptyState title="Проверок пока нет" description="Нажмите «Check now» в карточке отслеживания, чтобы получить первое фото." />
      </section>
    );
  }

  return (
    <>
      <section className="panel section-stack">
        <div className="section-head">
          <div>
            <p className="eyebrow">Снимок #{latestSnapshot.id}</p>
            <h2>Последняя проверка: {details.item.title}</h2>
          </div>
          <div className="actions-row">
            <Link className="btn btn-ghost" to={`/tracked-items/${details.item.id}`}>
              К деталям
            </Link>
            <Link className="btn btn-ghost" to="/tracked-items">
              К списку
            </Link>
          </div>
        </div>

        <div className="meta-grid">
          <article>
            <p className="meta-label">Статус</p>
            <StatusBadge status={latestSnapshot.status} />
          </article>
          <article>
            <p className="meta-label">Время проверки</p>
            <p>{formatDateTime(latestSnapshot.checked_at)}</p>
          </article>
          <article>
            <p className="meta-label">Найдено зон</p>
            <p>{latestSnapshot.zone_count}</p>
          </article>
          <article>
            <p className="meta-label">Ошибка</p>
            <p>{latestSnapshot.error_message || "-"}</p>
          </article>
        </div>
      </section>

      <section className="panel section-stack">
        <h3>Интерактивная подсветка зон</h3>

        {zoneDiff && (
          <div className="filter-row">
            <button className={chipClass(showAdded)} type="button" onClick={() => setShowAdded((value) => !value)}>
              A добавлены ({zoneDiff.counts.added})
            </button>
            <button className={chipClass(showRemoved)} type="button" onClick={() => setShowRemoved((value) => !value)}>
              R удалены ({zoneDiff.counts.removed})
            </button>
            <button className={chipClass(showStable)} type="button" onClick={() => setShowStable((value) => !value)}>
              S стабильные ({zoneDiff.counts.stable})
            </button>
          </div>
        )}

        {zoneError && <p className="error-text">{zoneError}</p>}

        {screenshotUrl ? (
          <div className="overlay-canvas">
            <img
              src={screenshotUrl}
              alt="Скриншот карты"
              className="preview-image preview-image-overlay"
              onLoad={(event) => {
                const img = event.currentTarget;
                setImageSize({ width: img.naturalWidth, height: img.naturalHeight });
              }}
            />

            {zoneDiff && imageSize && (
              <svg
                className="zone-overlay"
                viewBox={`0 0 ${imageSize.width} ${imageSize.height}`}
                preserveAspectRatio="xMidYMid meet"
                aria-hidden="true"
              >
                {visibleZones.map((zone, idx) => {
                  const points = zone.polygon.map((point) => `${point[0]},${point[1]}`).join(" ");
                  const color = zoneColor(zone.status);
                  return (
                    <g
                      key={`${zone.status}-${zone.label}-${idx}`}
                      onMouseEnter={() => setHoveredZone(zone)}
                      onMouseLeave={() => setHoveredZone(null)}
                    >
                      <polygon points={points} fill={color} fillOpacity={zone.status === "removed" ? 0.08 : 0.16} stroke={color} strokeWidth={2} />
                      <circle cx={zone.centroid_x} cy={zone.centroid_y} r={4} fill={color} />
                    </g>
                  );
                })}
              </svg>
            )}
          </div>
        ) : (
          <p className="muted">Файл скриншота не найден.</p>
        )}

        <div className="zone-hover-card">
          {hoveredZone ? (
            <>
              <p><strong>{zoneStatusText(hoveredZone.status)}</strong></p>
              <p>Появилась: {formatDateTime(hoveredZone.appeared_at)}</p>
              <p>Обновилась: {formatDateTime(hoveredZone.updated_at)}</p>
              <p>Последний раз видна: {formatDateTime(hoveredZone.last_seen_at)}</p>
              <p>Площадь: {Math.round(hoveredZone.area)}</p>
            </>
          ) : (
            <p className="muted">Наведите курсор на зону, чтобы увидеть детали.</p>
          )}
        </div>
      </section>

      <section className="panel section-stack">
        <h3>Фото с обводкой зон</h3>
        {processedUrl ? <img src={processedUrl} alt="Зоны на карте" className="preview-image preview-image-capped" /> : <p className="muted">Обработанное изображение отсутствует.</p>}
      </section>

      <section className="panel section-stack">
        <h3>Diff изображение</h3>
        {diffUrl ? <img src={diffUrl} alt="Diff зон" className="preview-image preview-image-capped" /> : <p className="muted">Для этого snapshot diff отсутствует.</p>}
      </section>
    </>
  );
}
