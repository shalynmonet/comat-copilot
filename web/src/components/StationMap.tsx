import { MapContainer, TileLayer, CircleMarker, Tooltip, Polyline } from "react-leaflet";
import type { Station } from "../api";

interface Props {
  stations: Station[];
  sourceCode?: string | null;
  destCode?: string | null;
}

const NETWORK_CENTER: [number, number] = [36.5, -92];

export function StationMap({ stations, sourceCode, destCode }: Props) {
  const source = stations.find((s) => s.code === sourceCode);
  const dest = stations.find((s) => s.code === destCode);

  return (
    <MapContainer center={NETWORK_CENTER} zoom={5} scrollWheelZoom={true}>
      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      />
      {stations.map((s) => (
        <CircleMarker
          key={s.code}
          center={[s.lat, s.lon]}
          radius={s.has_maintenance ? 10 : 6}
          pathOptions={{
            color: s.has_maintenance ? "#3b82f6" : "#64748b",
            fillColor: s.has_maintenance ? "#3b82f6" : "#64748b",
            fillOpacity: 0.85,
          }}
        >
          <Tooltip>
            <strong>{s.code}</strong> — {s.name}
            {s.has_maintenance ? " (maintenance base)" : ""}
          </Tooltip>
        </CircleMarker>
      ))}
      {source && dest && (
        <Polyline
          positions={[
            [source.lat, source.lon],
            [dest.lat, dest.lon],
          ]}
          pathOptions={{ color: "#ef4444", weight: 3, dashArray: "6 6" }}
        />
      )}
    </MapContainer>
  );
}
