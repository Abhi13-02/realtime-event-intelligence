// src/pages/HomeFeed.jsx
import { useEffect, useState } from "react";
import { alertsApi } from "../services/alerts";
import AlertCard from "../components/AlertCard";
import { useWebSocket } from '../context/WebSocketContext';

export default function HomeFeed() {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  
  const { latestAlert, isConnected } = useWebSocket(); 

  useEffect(() => {
    if (latestAlert) {
      setAlerts(prevAlerts => [latestAlert, ...prevAlerts]);
    }
  }, [latestAlert]);

  useEffect(() => {
    loadAlerts();
  }, []);

  const loadAlerts = async () => {
    try {
      setLoading(true);
      const response = await alertsApi.getAlerts(1, 20);
      setAlerts(response.data || []); 
    } catch (error) {
      console.error("Failed to load alerts.", error);
      setAlerts([
        { id: 1, headline: "SpaceX Launches New Rocket", summary: "A successful launch...", source_name: "TechCrunch", url: "#", relevance_score: 0.95 },
        { id: 2, headline: "AI Models Getting Faster", summary: "New optimization...", source_name: "Wired", url: "#", relevance_score: 0.82 },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id) => {
    setAlerts(alerts.filter((a) => a.id !== id));
    try {
      await alertsApi.deleteAlert(id);
    } catch (error) {
      console.error("Failed to delete alert", error);
    }
  };

  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-3xl font-bold font-orbitron text-transparent bg-clip-text bg-gradient-to-r from-white to-white/70 tracking-wide">
          LIVE FEED
        </h1>
        <div className={`flex items-center space-x-2 text-xs font-orbitron tracking-widest uppercase ${isConnected ? 'text-app-cyan' : 'text-white/40'}`}>
          <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-app-cyan shadow-[0_0_8px_rgba(0,240,255,0.8)] animate-pulse' : 'bg-white/20'}`}></div>
          <span>{isConnected ? 'System Online' : 'Connecting...'}</span>
        </div>
      </div>

      {loading ? (
        <div className="text-center py-12 text-app-cyan font-orbitron tracking-widest animate-pulse">
          INITIALIZING DATASTREAM...
        </div>
      ) : (
        <div className="space-y-5">
          {alerts.map((alert) => (
            <AlertCard key={alert.id} alert={alert} onDelete={handleDelete} />
          ))}
          {alerts.length === 0 && (
            <div className="glass-card text-center py-12 text-white/50 border-dashed border-white/20 font-dm">
              No active alerts in the datastream.
            </div>
          )}
        </div>
      )}
    </div>
  );
}