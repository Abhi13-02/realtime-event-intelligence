// src/layouts/MainLayout.jsx
import { Outlet, Link, useLocation } from "react-router-dom";
import { UserButton } from "@clerk/clerk-react"; // <-- Import Clerk's button

export default function MainLayout() {
  const location = useLocation();

  const navLinkStyle = (path) => {
    const isActive = location.pathname === path;
    return `block p-3 rounded-lg cursor-pointer transition-all duration-300 font-orbitron text-sm tracking-wider ${
      isActive
        ? "bg-app-cyan/10 text-app-cyan border border-app-cyan/30"
        : "text-white/50 hover:bg-white/5 hover:text-white"
    }`;
  };

  const mobileNavLinkStyle = (path) => {
    const isActive = location.pathname === path;
    return `flex flex-col items-center p-2 text-xs font-orbitron tracking-widest transition-all ${
      isActive ? "text-app-cyan" : "text-white/40 hover:text-white"
    }`;
  };

  return (
    <div className="relative min-h-screen w-full overflow-hidden bg-app-bg text-white">
      {/* 1. Global Background Effects */}
      <div className="absolute inset-0 bg-grid-pattern z-0" />
      <div className="absolute top-[-100px] right-[-100px] w-[500px] h-[500px] rounded-full opacity-20 blur-[120px] bg-app-cyan pointer-events-none z-0" />
      <div className="absolute bottom-[-100px] left-[-100px] w-[400px] h-[400px] rounded-full opacity-10 blur-[100px] bg-app-pink pointer-events-none z-0" />

      <div className="relative z-10 flex flex-col md:flex-row min-h-screen">
        {/* --- MOBILE HEADER (Visible only on phones) --- */}
        <header className="md:hidden glass-card m-4 p-4 flex justify-between items-center z-20 animate-fade-up">
          <h2 className="text-xl font-bold font-orbitron text-transparent bg-clip-text bg-gradient-to-r from-app-cyan to-app-pink">
            TrendyTopics
          </h2>
          {/* Clerk User Button for Mobile */}
          <UserButton afterSignOutUrl="/" />
        </header>

        {/* --- DESKTOP SIDEBAR (Visible only on larger screens) --- */}
        <nav className="glass-card hidden md:flex flex-col w-64 fixed h-[calc(100vh-32px)] m-4 p-6 z-20">
          <h2 className="text-2xl font-bold font-orbitron text-transparent bg-clip-text bg-gradient-to-r from-app-cyan to-app-pink mb-8">
            TrendyTopics
          </h2>

          <ul className="space-y-3 flex-1">
            <li>
              <Link to="/" className={navLinkStyle("/")}>
                Live Alerts
              </Link>
            </li>
            <li>
              <Link to="/topics" className={navLinkStyle("/topics")}>
                Manage Topics
              </Link>
            </li>
            <li>
              <Link to="/profile" className={navLinkStyle("/profile")}>
                Profile Settings
              </Link>
            </li>
          </ul>

          {/* Clerk User Button for Desktop */}
          <div className="mt-auto pt-6 border-t border-white/10 flex items-center gap-4">
            <UserButton afterSignOutUrl="/" />
            <span className="text-xs font-orbitron tracking-widest text-white/50 uppercase">
              System Access
            </span>
          </div>
        </nav>

        {/* Main Content Area */}
        <main className="flex-1 p-4 md:p-8 md:ml-[280px] pb-24 md:pb-8 overflow-y-auto min-h-screen animate-fade-up">
          <Outlet />
        </main>

        {/* Mobile Bottom Navigation */}
        <nav className="md:hidden glass-card fixed bottom-4 left-4 right-4 flex justify-around items-center h-16 z-[9999]">
          <Link to="/" className={mobileNavLinkStyle("/")}>
            <span>FEED</span>
          </Link>
          <Link to="/topics" className={mobileNavLinkStyle("/topics")}>
            <span>TOPICS</span>
          </Link>
          <Link to="/profile" className={mobileNavLinkStyle("/profile")}>
            <span>PROFILE</span>
          </Link>
        </nav>
      </div>
    </div>
  );
}
