// src/pages/TopicDeepDive.jsx
import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { alertsApi } from "../services/alerts";
import { intelligenceApi } from "../services/intelligence";
import { topicsApi } from "../services/topics";
import { useWebSocket } from "../context/WebSocketContext";
import AlertCard from "../components/AlertCard";
import SubThemeArticlesModal from "../components/SubThemeArticlesModal";

export default function TopicDeepDive() {
  const { topicId } = useParams(); // Grabs the ID from the URL

  const [topicName, setTopicName] = useState("LOADING PROTOCOL...");
  const [topicSensitivity, setTopicSensitivity] = useState("");
  const [alerts, setAlerts] = useState([]);
  const [subThemes, setSubThemes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [discovering, setDiscovering] = useState(false);
  const [discoveryMsg, setDiscoveryMsg] = useState(null);
  const [selectedSubTheme, setSelectedSubTheme] = useState(null);

  // Pagination states for Live Datastream
  const [alertsPage, setAlertsPage] = useState(1);
  const [alertsTotalPages, setAlertsTotalPages] = useState(1);

  const { latestAlert, isConnected } = useWebSocket();

  // 1. WebSocket Filter: Only inject alerts that match THIS topic if on page 1
  useEffect(() => {
    if (latestAlert && latestAlert.topic_id === topicId && alertsPage === 1) {
      setAlerts((prev) => [latestAlert, ...prev]);
    }
  }, [latestAlert, topicId, alertsPage]);

  // 2. Fetch Intelligence Data
  useEffect(() => {
    const loadIntelData = async () => {
      try {
        setLoading(true);
        const intelData = await intelligenceApi.getTopicIntelligence(topicId);
        setSubThemes(intelData.sub_themes || []);
        setTopicName(intelData.topic_name || "UNKNOWN TOPIC");
        setTopicSensitivity(intelData.sensitivity || "");
      } catch (error) {
        console.error("Failed to load Intelligence data:", error);
        setTopicName("SYSTEM ERROR");
      } finally {
        setLoading(false);
      }
    };

    if (topicId) loadIntelData();
  }, [topicId]);

  // 3. Fetch Alerts (Triggered on mount, topicId change, or alertsPage change)
  useEffect(() => {
    const loadAlerts = async () => {
      try {
        const alertsData = await alertsApi.getAlerts(alertsPage, 20, topicId);
        setAlerts(alertsData.data || []);
        setAlertsTotalPages(Math.ceil((alertsData.total_count || 0) / 20) || 1);
      } catch (error) {
        console.error("Failed to load alerts:", error);
      }
    };

    if (topicId) loadAlerts();
  }, [topicId, alertsPage]);

  const handleDelete = async (id) => {
    setAlerts(alerts.filter((a) => a.id !== id));
    try {
      await alertsApi.deleteAlert(id);
    } catch (error) {
      console.error("Failed to delete alert", error);
    }
  };

  // 3. Trigger sub-theme discovery and refresh clusters
  const handleDiscovery = async () => {
    if (discovering) return;
    setDiscovering(true);
    setDiscoveryMsg(null);
    try {
      await topicsApi.triggerDiscovery(topicId);
      // Re-fetch intelligence data so new sub-themes appear instantly
      const intelData = await intelligenceApi.getTopicIntelligence(topicId);
      setSubThemes(intelData.sub_themes || []);
      setDiscoveryMsg({ type: "success", text: "Narrative clusters updated." });
    } catch (error) {
      console.error("Discovery failed:", error);
      const detail =
        error.response?.data?.detail ||
        error.response?.data?.error ||
        "Discovery task failed. Try again.";
      setDiscoveryMsg({ type: "error", text: detail });
    } finally {
      setDiscovering(false);
      // Auto-dismiss the message after 5 seconds
      setTimeout(() => setDiscoveryMsg(null), 5000);
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
            <div className="flex items-center gap-3 mt-2">
              <p className="text-white/50 font-dm text-sm">
                Deep Dive Analytics &amp; Live Sub-theme Clustering
              </p>
              {topicSensitivity && (
                <span className="text-[10px] font-orbitron tracking-wider text-app-cyan bg-app-cyan/10 border border-app-cyan/30 px-2 py-0.5 rounded uppercase">
                  FILTER: {topicSensitivity}
                </span>
              )}
            </div>
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
              <>
                {alerts.map((alert) => (
                  <AlertCard
                    key={alert.id}
                    alert={alert}
                    onDelete={handleDelete}
                  />
                ))}
                
                {/* Pagination Controls */}
                {alertsTotalPages > 1 && (
                  <div className="flex justify-between items-center mt-6 p-4 glass-card border border-white/10 rounded-lg">
                    <button
                      onClick={() => setAlertsPage((p) => Math.max(1, p - 1))}
                      disabled={alertsPage === 1}
                      className={`px-4 py-2 text-xs font-orbitron tracking-widest rounded ${
                        alertsPage === 1
                          ? "text-white/20 cursor-not-allowed"
                          : "text-app-cyan hover:bg-app-cyan/10 hover:border-app-cyan/50"
                      } border border-transparent transition-all uppercase`}
                    >
                      &larr; Prev
                    </button>
                    <span className="text-xs font-dm text-white/50 uppercase">
                      Page <span className="text-white font-bold">{alertsPage}</span> of {alertsTotalPages}
                    </span>
                    <button
                      onClick={() => setAlertsPage((p) => Math.min(alertsTotalPages, p + 1))}
                      disabled={alertsPage === alertsTotalPages}
                      className={`px-4 py-2 text-xs font-orbitron tracking-widest rounded ${
                        alertsPage === alertsTotalPages
                          ? "text-white/20 cursor-not-allowed"
                          : "text-app-cyan hover:bg-app-cyan/10 hover:border-app-cyan/50"
                      } border border-transparent transition-all uppercase`}
                    >
                      Next &rarr;
                    </button>
                  </div>
                )}
              </>
            )}
          </div>

          {/* RIGHT SIDE: Narrative Clusters (Sub-Themes) */}
          <div
            className="space-y-5 animate-fade-up"
            style={{ animationDelay: "0.2s" }}
          >
            <div className="border-b border-white/10 pb-3 mb-4 flex items-center justify-between">
              <h2 className="text-lg font-bold font-orbitron text-white tracking-widest uppercase flex items-center gap-2">
                <span className="w-2 h-2 bg-app-cyan rounded-full shadow-[0_0_8px_rgba(0,240,255,0.8)]"></span>
                Narrative Clusters
              </h2>
              <button
                id="discover-narratives-btn"
                onClick={handleDiscovery}
                disabled={discovering}
                className="discover-btn group"
              >
                {discovering ? (
                  <>
                    <svg className="discover-btn-spinner" viewBox="0 0 24 24" fill="none">
                      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" strokeDasharray="31.4 31.4" strokeLinecap="round" />
                    </svg>
                    <span>Scanning...</span>
                  </>
                ) : (
                  <>
                    <svg className="discover-btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="11" cy="11" r="8" />
                      <path d="M21 21l-4.35-4.35" />
                      <path d="M11 8v6M8 11h6" />
                    </svg>
                    <span>Discover</span>
                  </>
                )}
              </button>
            </div>

            {/* Discovery status message */}
            {discoveryMsg && (
              <div
                className={`discovery-msg ${discoveryMsg.type === "success" ? "discovery-msg-success" : "discovery-msg-error"}`}
              >
                <span className="text-[10px] font-orbitron tracking-widest uppercase">
                  {discoveryMsg.type === "success" ? "✓ " : "✕ "}
                  {discoveryMsg.text}
                </span>
              </div>
            )}

            {subThemes.length === 0 ? (
              <div className="glass-card text-center py-12 text-white/50 border-dashed border-white/20 font-dm">
                Insufficient data for narrative clustering.
              </div>
            ) : (
              subThemes.map((theme) => (
                <div
                  key={theme.id}
                  className="glass-card p-5 border-l-2 border-l-app-cyan cursor-pointer hover:bg-white/5 transition-colors"
                  onClick={() => setSelectedSubTheme(theme)}
                >
                  <div className="flex justify-between items-start mb-2">
                    <h3 className="text-lg font-bold text-white font-dm uppercase tracking-wide">
                      {theme.label}
                    </h3>
                    <div className="flex items-center gap-6">
                      <div className="flex flex-col items-end">
                        <span className="text-[10px] font-orbitron tracking-widest text-white/50 uppercase">
                          Sentiment
                        </span>
                        <span className={`font-bold font-dm ${
                          theme.sentiment_score > 0 ? "text-app-cyan" : theme.sentiment_score < 0 ? "text-app-pink" : "text-white/50"
                        }`}>
                          {theme.sentiment_score != null 
                            ? `${theme.sentiment_score > 0 ? "+" : ""}${Math.round(theme.sentiment_score * 100)}%` 
                            : "N/A"}
                        </span>
                      </div>
                      <div className="flex flex-col items-end">
                        <span className="text-[10px] font-orbitron tracking-widest text-white/50 uppercase">
                          Volume
                        </span>
                        <span className="text-app-cyan font-bold font-dm">
                          {theme.total_volume}
                        </span>
                      </div>
                    </div>
                  </div>

                  <p className="text-sm text-white/60 font-dm mb-4">
                    {theme.description}
                  </p>

                  {/* Representative Article Callout */}
                  {theme.representative_article && (
                    <div className="mt-4 p-3 bg-[#0b0e1a]/50 rounded-lg border border-white/5 flex gap-3 items-start">
                      {theme.representative_article.image_url && (
                        <div className="w-16 h-16 rounded overflow-hidden flex-shrink-0 border border-white/10">
                          <img 
                            src={theme.representative_article.image_url} 
                            alt="" 
                            className="w-full h-full object-cover"
                            onError={(e) => { e.target.style.display = 'none'; }}
                          />
                        </div>
                      )}
                      <div>
                        <span className="block text-[10px] font-orbitron tracking-widest text-app-pink mb-1 uppercase">
                          Representative Article
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
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* Articles Modal */}
      <SubThemeArticlesModal
        isOpen={!!selectedSubTheme}
        onClose={() => setSelectedSubTheme(null)}
        topicId={topicId}
        subTheme={selectedSubTheme}
      />
    </div>
  );
}
