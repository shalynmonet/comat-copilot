import type { ExpiringPart } from "../api";

interface Props {
  parts: ExpiringPart[];
  selectedSerial: string | null;
  onSelect: (part: ExpiringPart) => void;
}

export function ExpiryQueue({ parts, selectedSerial, onSelect }: Props) {
  return (
    <div className="panel">
      <h2>Expiring Parts</h2>
      {parts.length === 0 ? (
        <p className="empty-hint">Nothing expiring in the window.</p>
      ) : (
        <ul className="queue-list">
          {parts.map((p) => (
            <li
              key={p.serial}
              className={p.serial === selectedSerial ? "selected" : ""}
              onClick={() => onSelect(p)}
            >
              <div className="queue-days" data-urgent={p.days_left <= 2}>
                {p.days_left}d
              </div>
              <div className="queue-info">
                <div className="queue-title">{p.description}</div>
                <div className="queue-sub">
                  {p.tail_number} · {p.station}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
