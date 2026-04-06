// src/components/AlertCard.jsx
export default function AlertCard({ alert, onDelete }) {
  return (
    <div className="glass-card p-5 animate-fade-up">
      <div className="flex justify-between items-start gap-4">
        <div>
          <span className="inline-block px-2 py-1 text-[10px] font-orbitron tracking-widest uppercase rounded bg-blue-500/10 border border-blue-500/30 text-blue-400 mb-3">
            {alert.source_name || "News Source"}
          </span>
          <h3 className="text-lg font-bold text-white leading-tight font-dm">
            {alert.headline}
          </h3>
        </div>
        <div className="flex flex-col items-end flex-shrink-0">
          <span className="text-xs font-orbitron font-bold text-app-cyan bg-app-cyan/10 border border-app-cyan/20 px-2 py-1 rounded">
            {alert.relevance_score ? `${Math.round(alert.relevance_score * 100)}% Match` : "New"}
          </span>
        </div>
      </div>
      
      <p className="mt-3 text-sm text-white/60 line-clamp-3 font-dm">
        {alert.summary}
      </p>

      <div className="mt-5 flex justify-between items-center pt-4 border-t border-white/10">
        <a 
          href={alert.url} 
          target="_blank" 
          rel="noopener noreferrer"
          className="text-xs font-orbitron tracking-wider text-app-cyan hover:text-white transition-colors"
        >
          READ FULL ARTICLE &rarr;
        </a>
        <button 
          onClick={() => onDelete(alert.id)}
          className="text-xs font-orbitron tracking-wider text-app-pink hover:text-white border border-app-pink/30 hover:bg-app-pink/20 px-3 py-1.5 rounded transition-all"
        >
          DISMISS
        </button>
      </div>
    </div>
  );
}