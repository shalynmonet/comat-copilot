import type { PlanEvent } from "../api";

interface Props {
  events: PlanEvent[];
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function EventTimeline({ events }: Props) {
  return (
    <div className="timeline-panel">
      <h2>Event Timeline</h2>
      {events.length === 0 ? (
        <p className="empty-hint">No decisions logged yet for this plan.</p>
      ) : (
        <ul className="timeline-list">
          {events.map((e) => (
            <li key={e.id}>
              <div className="event-type">{e.event_type}</div>
              <div className="event-time">{formatTime(e.created_at)}</div>
              {e.detail && <div>{e.detail}</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
