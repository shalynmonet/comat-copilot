import type { HandoffRoute, ShipmentStatus } from "../api";
import { TRACKER_STEPS } from "../api";

interface Props {
  handoffRoute: HandoffRoute;
  shipmentStatus: ShipmentStatus | null;
  awbNumber: string | null;
}

export function ShipmentTracker({ handoffRoute, shipmentStatus, awbNumber }: Props) {
  const steps = TRACKER_STEPS[handoffRoute];
  const currentIndex = shipmentStatus ? steps.findIndex((s) => s.step === shipmentStatus) : -1;

  return (
    <div className="tracker">
      <div className="tracker-header">
        <span>Shipment Tracker</span>
        {awbNumber && <span className="awb-tag">AWB {awbNumber}</span>}
      </div>
      <div className="tracker-strip">
        {steps.map((s, i) => {
          const state = i < currentIndex ? "done" : i === currentIndex ? "current" : "pending";
          return (
            <div key={s.step} className={`tracker-step ${state}`}>
              <div className="tracker-dot" />
              <div className="tracker-label">{s.label}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
