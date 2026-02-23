
import React from 'react';
import { Settings, Menu, Edit3, Clock, Lock } from 'lucide-react';

interface SidebarProps {
  isOpen: boolean;
  toggleSidebar: () => void;
  onNewChat: () => void;
  isAuthenticated: boolean;
}

export const Sidebar: React.FC<SidebarProps> = ({ isOpen, toggleSidebar, onNewChat, isAuthenticated }) => {
  return (
    <>
      {/* Mobile Toggle */}
      <button 
        onClick={toggleSidebar} 
        className="lg:hidden fixed top-4 left-4 z-50 p-2 bg-black/15 backdrop-blur-md rounded-md text-white border border-white/20"
      >
        <Menu size={20} />
      </button>

      <div className={`
        fixed lg:static inset-y-0 left-0 z-40
        w-64 bg-black/10 backdrop-blur-lg border-r border-white/10 transform transition-transform duration-300 ease-in-out
        ${isOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
        flex flex-col
      `}>
        <div className="p-6 flex items-center justify-end h-24">
           <button 
            onClick={onNewChat}
            className="flex flex-col items-center gap-2 text-gray-200 hover:text-white transition-colors group"
           >
            <div className="w-10 h-10 bg-white/5 border border-white/10 rounded-xl flex items-center justify-center group-hover:bg-white/10 group-hover:border-white/30 transition-all shadow-sm">
               <Edit3 size={18} />
            </div>
            <span className="text-xs font-bold tracking-wide uppercase opacity-80">new chat</span>
           </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-2 custom-scrollbar">
          {isAuthenticated && (
            <>
                <div className="text-xs font-bold text-white/60 mb-4 pl-3 uppercase tracking-wider">History</div>
                
                <ul className="space-y-1">
                    {['Trip to Fiji', 'Weekend in Paris', 'Japan Itinerary', 'NYC Business Trip', 'Bali Honeymoon'].map((item, idx) => (
                    <li key={idx}>
                        <button className="flex items-center gap-3 w-full text-left px-3 py-3 text-gray-300 hover:bg-white/10 hover:text-white rounded-lg transition-all text-base group">
                        <Clock size={16} className="opacity-60 group-hover:opacity-100 transition-opacity" />
                        <span className="truncate font-medium">{item}</span>
                        </button>
                    </li>
                    ))}
                </ul>
            </>
          )}
        </div>

        <div className="p-4 border-t border-white/10">
          <button className="flex items-center gap-3 w-full text-left p-3 text-gray-300 hover:text-white hover:bg-white/10 rounded-lg transition-all text-sm font-medium">
            <Settings size={16} />
            <span>Settings</span>
          </button>
        </div>
      </div>
      
      {/* Overlay for mobile */}
      {isOpen && (
        <div 
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-30 lg:hidden"
          onClick={toggleSidebar}
        />
      )}
    </>
  );
};
