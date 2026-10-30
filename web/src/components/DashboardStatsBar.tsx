import type { DashboardStats } from "../api";

interface Props {
  stats: DashboardStats | null;
}

function discrepancyLevel(rate: number): "low" | "mid" | "high" {
  if (rate >= 0.3) return "high";
  if (rate >= 0.15) return "mid";
  return "low";
}

export function DashboardStatsBar({ stats }: Props) {
  if (!stats) return null;

  const noteworthyStations = stats.station_discrepancy_rates.filter((s) => s.discrepancy_rate > 0);

  return (
    <div className="stats-strip">
      <div className="stat-tile">
        <span className="stat-value">{stats.aogs_avoided}</span>
        <span className="stat-label">AOGs avoided</span>
      </div>
      <div className="stat-tile">
        <span className="stat-value">{stats.planeside_runs_avoided}</span>
        <span className="stat-label">Plane-side runs avoided</span>
      </div>
      <div className="stat-tile">
        <span className="stat-value">{stats.phantom_parts_caught}</span>
        <span className="stat-label">Phantom parts caught</span>
      </div>
      <div className="stat-tile">
        <span className="stat-value">{stats.picks_verified_by_photo}</span>
        <span className="stat-label">Picks verified by photo</span>
      </div>
      <div className="stat-tile">
        <span className="stat-value">{stats.discrepancies_caught_at_pick}</span>
        <span className="stat-label">Discrepancies caught at pick</span>
      </div>
      <div className="stat-tile">
        <span className="stat-value">${stats.shelf_life_value_saved.toFixed(0)}</span>
        <span className="stat-label">Shelf-life value saved</span>
      </div>
      <div className="stat-tile">
        <span className="stat-value">
          {stats.failure_response_time_median_minutes === null
            ? "—"
            : `${stats.failure_response_time_median_minutes.toFixed(0)}m`}
        </span>
        <span className="stat-label">Failure response time (median)</span>
      </div>
      {noteworthyStations.length > 0 && (
        <div className="stat-tile">
          <span className="stat-label">Station discrepancy rates</span>
          <div className="discrepancy-list">
            {noteworthyStations.map((s) => (
              <span key={s.station} className="discrepancy-chip" data-level={discrepancyLevel(s.discrepancy_rate)}>
                {s.station} {(s.discrepancy_rate * 100).toFixed(0)}%
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
