// src/components/AlertCard.jsx
export default function AlertCard({ alert, onDelete }) {
  const hasImage = !!alert.image_url;

  return (
    <div className="glass-card group overflow-hidden animate-fade-up">
      <div className={`flex flex-col ${hasImage ? 'sm:flex-row' : ''}`}>
        {/* Optional Image Sidebar/Top */}
        {hasImage && (
          <div className="sm:w-52 h-48 sm:h-auto article-img-container rounded-none flex-shrink-0">
            <img 
              src={alert.image_url} 
              alt="" 
              className="w-full h-full object-cover img-zoom-hover"
              onError={(e) => { e.target.style.display = 'none'; }}
            />
            <div className="article-img-overlay" />
          </div>
        )}

        {/* Content Area */}
        <div className={`p-5 flex-1 flex flex-col ${hasImage ? 'sm:pl-1' : ''}`}>
          <div className="flex justify-between items-start gap-4 mb-3">
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-2">
                <span className="inline-block px-2 py-0.5 text-[9px] font-orbitron tracking-widest uppercase rounded bg-app-cyan/10 border border-app-cyan/30 text-app-cyan">
                  {alert.source_name || "News Source"}
                </span>
                {hasImage && (
                  <span className="px-1.5 py-0.5 text-[9px] font-orbitron tracking-widest uppercase rounded bg-white/5 border border-white/10 text-white/40">
                    MEDIA ATTACHED
                  </span>
                )}
              </div>
              <h3 className="text-lg font-bold text-white leading-tight font-dm group-hover:text-app-cyan transition-colors line-clamp-2">
                {alert.headline}
              </h3>
            </div>
            <div className="flex flex-col items-end flex-shrink-0">
              <span className="text-[10px] font-orbitron font-bold text-app-cyan bg-app-cyan/5 border border-app-cyan/10 px-2 py-1 rounded shadow-[0_0_10px_rgba(0,240,255,0.05)]">
                {alert.relevance_score ? `${Math.round(alert.relevance_score * 100)}% MATCH` : "NEW"}
              </span>
            </div>
          </div>
          
          <p className="text-sm text-white/50 line-clamp-2 font-dm flex-1 mb-4">
            {alert.summary}
          </p>

          <div className="flex justify-between items-center pt-3 border-t border-white/5">
            <a 
              href={alert.url} 
              target="_blank" 
              rel="noopener noreferrer"
              className="text-[10px] font-orbitron tracking-widest text-white/40 group-hover:text-app-cyan transition-all flex items-center gap-2 uppercase"
            >
              Access Intelligence <span>&rarr;</span>
            </a>
            {onDelete && (
              <button 
                onClick={() => onDelete(alert.id)}
                className="text-[10px] font-orbitron tracking-widest text-app-pink/60 hover:text-app-pink transition-colors uppercase"
              >
                Dismiss
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}