import { useEffect, useState } from "react";
import { intelligenceApi } from "../services/intelligence";
import AlertCard from "./AlertCard";

export default function SubThemeArticlesModal({ isOpen, onClose, topicId, subTheme }) {
  const [articles, setArticles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!isOpen || !subTheme) return;

    const fetchArticles = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await intelligenceApi.getSubThemeArticles(topicId, subTheme.id);
        setArticles(response.data || []);
      } catch (err) {
        console.error("Failed to fetch articles:", err);
        setError("Failed to load articles.");
      } finally {
        setLoading(false);
      }
    };

    fetchArticles();
  }, [isOpen, topicId, subTheme]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="bg-[#0b0e1a] border border-app-cyan/30 rounded-xl shadow-[0_0_40px_rgba(0,240,255,0.15)] w-full max-w-4xl max-h-[85vh] flex flex-col overflow-hidden animate-fade-up">
        
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-white/10 bg-white/5">
          <div>
            <h2 className="text-2xl font-bold font-orbitron text-transparent bg-clip-text bg-gradient-to-r from-app-cyan to-white uppercase tracking-wider">
              {subTheme.label || "Sub-theme Details"}
            </h2>
            <p className="text-sm text-white/50 font-dm mt-1">
              {subTheme.description}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-full transition-colors"
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="p-6 overflow-y-auto flex-1 custom-scrollbar">
          {loading ? (
            <div className="py-20 text-center text-app-cyan font-orbitron tracking-widest animate-pulse">
              EXTRACTING ARTICLES...
            </div>
          ) : error ? (
            <div className="py-20 text-center text-app-pink font-dm">
              {error}
            </div>
          ) : articles.length === 0 ? (
            <div className="py-20 text-center text-white/50 font-dm">
              No articles found for this cluster.
            </div>
          ) : (
            <div className="space-y-4">
              {articles.map((article) => (
                <AlertCard
                  key={article.id}
                  alert={{
                    ...article,
                    relevance_score: article.similarity_to_centroid,
                    source_name: article.membership_type === "news" 
                      ? article.source_name 
                      : `REDDIT | ${article.source_name}`
                  }}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
