
import React from 'react';

interface HeaderProps {
  isAuthenticated: boolean;
  onLogin: () => void;
  onLogout: () => void;
  activeView: "chat" | "registry";
  onChangeView: (view: "chat" | "registry") => void;
}

export const Header: React.FC<HeaderProps> = ({
  isAuthenticated,
  onLogin,
  onLogout,
  activeView,
  onChangeView,
}) => {
  return (
    <header className="relative z-20 flex justify-between items-center py-6 px-8 w-full">
      <div className="flex items-center gap-2">
        <span className="font-bold text-2xl text-white drop-shadow-md tracking-tight">Multi-agent Travel</span>
        <span className="bg-white/20 text-white text-xs font-semibold px-3 py-1 rounded-md backdrop-blur-sm border border-white/10 shadow-sm">Planner</span>
      </div>
      <div className="flex items-center gap-6">
        <nav className="hidden md:flex items-center gap-2 text-sm font-medium text-gray-100 bg-black/20 border border-white/20 rounded-full p-1">
          <button
            onClick={() => onChangeView("chat")}
            className={`px-4 py-1.5 rounded-full transition-colors ${
              activeView === "chat" ? "bg-white text-sky-900 font-bold" : "text-white hover:bg-white/15"
            }`}
          >
            Chat
          </button>
          <button
            onClick={() => onChangeView("registry")}
            className={`px-4 py-1.5 rounded-full transition-colors ${
              activeView === "registry" ? "bg-white text-sky-900 font-bold" : "text-white hover:bg-white/15"
            }`}
          >
            Agent Registry
          </button>
        </nav>
        <div className="flex items-center gap-3 border-l border-white/20 pl-8">
            {!isAuthenticated ? (
                <>
                    <button onClick={onLogin} className="text-white text-sm font-medium px-4 py-2 rounded-full hover:bg-white/10 transition-all drop-shadow-sm">Sign Up</button>
                    <button onClick={onLogin} className="bg-white text-sky-900 text-sm font-bold px-4 py-2 rounded-full hover:bg-sky-50 transition-all shadow-md hover:shadow-lg">Log In</button>
                </>
            ) : (
                 <button onClick={onLogout} className="bg-white/10 text-white text-sm font-medium px-4 py-2 rounded-full hover:bg-white/20 transition-all backdrop-blur-sm border border-white/10">Sign Out</button>
            )}
        </div>
      </div>
    </header>
  );
};
