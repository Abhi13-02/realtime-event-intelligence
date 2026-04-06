// src/pages/TopicsDashboard.jsx
import { useEffect, useState } from "react";
import { topicsApi } from "../services/topics";
import TopicModal from "../components/TopicModal";

export default function TopicsDashboard() {
  const [topics, setTopics] = useState([]);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);

  useEffect(() => {
    loadTopics();
  }, []);

  const loadTopics = async () => {
    try {
      setLoading(true);
      const data = await topicsApi.getTopics(1, 20);
      setTopics(data.data || []); 
    } catch (error) {
      console.error("Failed to load topics:", error);
      setTopics([
        { id: "1", name: "Artificial Intelligence", description: "Tracking LLM and Groq releases", is_active: true },
        { id: "2", name: "Global Markets", description: "Stock market updates and tech sector trends", is_active: true },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id) => {
    setTopics(topics.filter((t) => t.id !== id));
    try {
      await topicsApi.deleteTopic(id);
    } catch (error) {
      console.error("Failed to delete topic", error);
    }
  };

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-10">
        <div>
          <h1 className="text-3xl font-bold font-orbitron text-transparent bg-clip-text bg-gradient-to-r from-white to-white/70 tracking-wide">
            TOPIC MATRIX
          </h1>
          <p className="text-white/50 mt-2 font-dm text-sm">
            Configure your datastream and notification nodes.
          </p>
        </div>
        <button
          className="bg-app-cyan/10 text-app-cyan border border-app-cyan/40 hover:bg-app-cyan/20 hover:shadow-[0_0_15px_rgba(0,240,255,0.3)] px-5 py-2.5 rounded-lg font-orbitron text-xs tracking-widest transition-all"
          onClick={() => setIsModalOpen(true)}
        >
          + INIT TOPIC
        </button>
      </div>

      {loading ? (
        <div className="text-center py-12 text-app-cyan font-orbitron tracking-widest animate-pulse">
          LOADING MATRIX...
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {topics.map((topic) => (
            <div
              key={topic.id}
              className="glass-card p-6 flex flex-col justify-between animate-fade-up"
            >
              <div>
                <div className="flex justify-between items-start mb-3">
                  <h3 className="text-lg font-bold font-dm text-white">
                    {topic.name}
                  </h3>
                  <span
                    className={`h-2.5 w-2.5 rounded-full ${topic.is_active !== false ? "bg-app-cyan shadow-[0_0_8px_rgba(0,240,255,0.8)]" : "bg-white/20"}`}
                  ></span>
                </div>
                <p className="text-sm text-white/60 font-dm mb-5 line-clamp-2">
                  {topic.description || "No description provided."}
                </p>

                {/* Cyberpunk Sentiment Badge */}
                <div className="flex gap-2">
                  <span className="text-[10px] font-orbitron tracking-wider text-app-pink bg-app-pink/10 border border-app-pink/30 px-2 py-1 rounded">
                    REDDIT SENTIMENT: TRACKING
                  </span>
                </div>
              </div>

              <div className="mt-6 flex justify-end gap-4 border-t border-white/10 pt-4">
                <button className="text-xs font-orbitron tracking-wider text-app-cyan hover:text-white transition-colors">
                  CONFIGURE
                </button>
                <button
                  onClick={() => handleDelete(topic.id)}
                  className="text-xs font-orbitron tracking-wider text-app-pink hover:text-white transition-colors"
                >
                  PURGE
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
      <TopicModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={loadTopics}
      />
    </div>
  );
}