// src/pages/TopicDeepDive.jsx
import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { alertsApi } from "../services/alerts";
import { intelligenceApi } from "../services/intelligence";
import { useWebSocket } from "../context/WebSocketContext";
import AlertCard from "../components/AlertCard";

export default function TopicDeepDive() {
  const { topicId } = useParams(); // Grabs the ID from the URL

  const [topicName, setTopicName] = useState("LOADING PROTOCOL...");
  const [alerts, setAlerts] = useState([]);
  const [subThemes, setSubThemes] = useState([]);
  const [loading, setLoading] = useState(true);

  const { latestAlert, isConnected } = useWebSocket();

  // 1. WebSocket Filter: Only inject alerts that match THIS topic
  useEffect(() => {
    if (latestAlert && latestAlert.topic_id === topicId) {
      setAlerts((prev) => [latestAlert, ...prev]);
    }
  }, [latestAlert, topicId]);

  // 2. Fetch the initial dual-data payloads
  useEffect(() => {
    const loadDeepDiveData = async () => {
      try {
        setLoading(true);
        // Fire both API calls at the exact same time for maximum speed
        const [alertsData, intelData] = await Promise.all([
          alertsApi.getAlerts(1, 20, topicId),
          intelligenceApi.getTopicIntelligence(topicId),
        ]);

        setAlerts(alertsData.data || []);
        setSubThemes(intelData.sub_themes || []);
        setTopicName(intelData.topic_name || "UNKNOWN TOPIC");
      } catch (error) {
        console.error("Failed to load Deep Dive data:", error);
        setTopicName("SYSTEM ERROR");
      } finally {
        setLoading(false);
      }
    };

    if (topicId) loadDeepDiveData();
  }, [topicId]);

  const handleDelete = async (id) => {
    setAlerts(alerts.filter((a) => a.id !== id));
    try {
      await alertsApi.deleteAlert(id);
    } catch (error) {
      console.error("Failed to delete alert", error);
    }
  };

  return (
    <div className="max-w-7xl mx-auto">
      {/* Header Section */}
      <div className="mb-8 animate-fade-up">
        <Link
          to="/topics"
          className="text-xs font-orbitron text-app-cyan hover:text-white transition-colors uppercase tracking-widest flex items-center gap-2 mb-4"
        >
          &larr; Return to Matrix
        </Link>
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl md:text-4xl font-bold font-orbitron text-transparent bg-clip-text bg-gradient-to-r from-app-cyan to-white tracking-wider uppercase">
              {topicName}
            </h1>
            <p className="text-white/50 mt-2 font-dm text-sm">
              Deep Dive Analytics & Live Sub-theme Clustering
            </p>
          </div>
          <div
            className={`flex items-center space-x-2 text-xs font-orbitron tracking-widest uppercase ${isConnected ? "text-app-cyan" : "text-white/40"}`}
          >
            <div
              className={`w-2 h-2 rounded-full ${isConnected ? "bg-app-cyan shadow-[0_0_8px_rgba(0,240,255,0.8)] animate-pulse" : "bg-white/20"}`}
            ></div>
            <span>{isConnected ? "NODE ONLINE" : "CONNECTING..."}</span>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="text-center py-20 text-app-cyan font-orbitron tracking-widest animate-pulse">
          SYNCING DATASTREAMS...
        </div>
      ) : (
        /* THE SPLIT SCREEN GRID */
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-8 items-start">
          {/* LEFT SIDE: Live Feed */}
          <div
            className="space-y-5 animate-fade-up"
            style={{ animationDelay: "0.1s" }}
          >
            <div className="border-b border-white/10 pb-3 mb-4">
              <h2 className="text-lg font-bold font-orbitron text-white tracking-widest uppercase flex items-center gap-2">
                <span className="w-2 h-2 bg-app-pink rounded-full shadow-[0_0_8px_rgba(255,0,127,0.8)]"></span>
                Live Datastream
              </h2>
            </div>

            {alerts.length === 0 ? (
              <div className="glass-card text-center py-12 text-white/50 border-dashed border-white/20 font-dm">
                No active alerts matching this topic.
              </div>
            ) : (
              alerts.map((alert) => (
                <AlertCard
                  key={alert.id}
                  alert={alert}
                  onDelete={handleDelete}
                />
              ))
            )}
          </div>

          {/* RIGHT SIDE: Narrative Clusters (Sub-Themes) */}
          <div
            className="space-y-5 animate-fade-up"
            style={{ animationDelay: "0.2s" }}
          >
            <div className="border-b border-white/10 pb-3 mb-4">
              <h2 className="text-lg font-bold font-orbitron text-white tracking-widest uppercase flex items-center gap-2">
                <span className="w-2 h-2 bg-app-cyan rounded-full shadow-[0_0_8px_rgba(0,240,255,0.8)]"></span>
                Narrative Clusters
              </h2>
            </div>

            {subThemes.length === 0 ? (
              <div className="glass-card text-center py-12 text-white/50 border-dashed border-white/20 font-dm">
                Insufficient data for narrative clustering.
              </div>
            ) : (
              subThemes.map((theme) => (
                <div
                  key={theme.id}
                  className="glass-card p-5 border-l-2 border-l-app-cyan"
                >
                  <div className="flex justify-between items-start mb-2">
                    <h3 className="text-lg font-bold text-white font-dm uppercase tracking-wide">
                      {theme.label}
                    </h3>
                    <div className="flex flex-col items-end">
                      <span className="text-[10px] font-orbitron tracking-widest text-white/50 uppercase">
                        Volume
                      </span>
                      <span className="text-app-cyan font-bold font-dm">
                        {theme.total_volume}
                      </span>
                    </div>
                  </div>

                  <p className="text-sm text-white/60 font-dm mb-4">
                    {theme.description}
                  </p>

                  <div className="flex flex-wrap gap-2 mb-4">
                    {theme.keywords.map((kw, i) => (
                      <span
                        key={i}
                        className="text-[10px] font-orbitron tracking-widest text-app-cyan/70 bg-app-cyan/5 px-2 py-1 rounded border border-app-cyan/20 uppercase"
                      >
                        {kw}
                      </span>
                    ))}
                  </div>

                  {/* Representative Article Callout */}
                  {theme.representative_article && (
                    <div className="mt-4 p-3 bg-[#0b0e1a]/50 rounded-lg border border-white/5">
                      <span className="block text-[10px] font-orbitron tracking-widest text-app-pink mb-1 uppercase">
                        Centroid Vector
                      </span>
                      <a
                        href={theme.representative_article.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm font-dm text-white hover:text-app-cyan transition-colors line-clamp-2"
                      >
                        {theme.representative_article.headline}
                      </a>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
