import React, { useState } from 'react';
import { Plus, Volume2, Send, X, Star } from 'lucide-react';

interface SuggestionCardsProps {
  onSelect: (text: string) => void;
}

export const SuggestionCards: React.FC<SuggestionCardsProps> = ({ onSelect }) => {
  const [inputValue, setInputValue] = useState('');

  const handleSend = () => {
    if (inputValue.trim()) {
      onSelect(inputValue);
    }
  };

  const CategoryBox = ({ title, items }: { title: string, items: string[] }) => (
    <div className="bg-white/5 p-4 rounded-lg border border-white/10 hover:bg-white/10 transition-colors group cursor-pointer">
      <h3 className="font-semibold text-white mb-2">{title}</h3>
      {items.map((item, i) => (
        <button 
          key={i} 
          onClick={() => onSelect(item)}
          className={`block w-full text-left text-sm text-white hover:underline decoration-white/50 underline-offset-2 transition-all ${i > 0 ? 'mt-1' : ''}`}
        >
          "{item}"
        </button>
      ))}
    </div>
  );

  return (
    <div className="bg-black/15 backdrop-blur-lg rounded-2xl shadow-xl border border-white/10 p-6 md:p-8 max-w-4xl mx-auto w-full mt-8 mb-4 animate-fade-in">
      <div className="flex justify-between items-start">
        <h2 className="text-3xl font-bold text-white drop-shadow-sm">Where to today?</h2>
        <button className="text-gray-400 hover:text-white transition-colors p-1 hover:bg-white/10 rounded-full">
          <X size={24} />
        </button>
      </div>
      
      <div className="mt-4 flex items-start gap-3">
        <span className="text-2xl filter drop-shadow-sm">⭐</span>
        <div className="text-white text-base leading-relaxed font-medium drop-shadow-sm">
           <p>Hey there, where would you like to go?</p>
           <p>I'm here to assist you in planning your experience.</p>
           <p>Ask me anything travel related.
        </p></div>
      </div>

      <div className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-4">
        <CategoryBox 
          title="Itineraries and trip planning"
          items={[
            "Suggest a 3-day weekend getaway from Gujarat.",
            "What's the best itinerary for Paris in April?"
          ]}
        />
        <CategoryBox 
          title="Accommodation"
          items={[
            "Find me budget hotels in Manali with good ratings.",
            "Suggest romantic stays near Eiffel Tower."
          ]}
        />
        <CategoryBox 
          title="Transport"
          items={[
            "What's the best way to reach Shimla from Delhi?",
            "Book a flight from Ahmedabad to Bali on 10th May."
          ]}
        />
        <CategoryBox 
          title="Local Experience / Culture"
          items={[
            "How to greet people in French?",
            "Are there any local festivals in Ubud this week?"
          ]}
        />
      </div>

      <div className="mt-8 relative">
        <div className="flex items-center bg-transparent border-2 border-white/20 focus-within:border-white/50 rounded-xl p-2 gap-3 transition-all group">
          <button className="flex-shrink-0 w-8 h-8 rounded-md bg-white/10 hover:bg-white/20 flex items-center justify-center text-gray-300 transition-colors">
            <Plus size={20} />
          </button>
          <button className="flex-shrink-0 text-gray-300 hover:text-white transition-colors p-1">
            <Volume2 size={20} />
          </button>
          <input 
            className="w-full bg-transparent border-none focus:ring-0 focus:outline-none text-white placeholder-gray-400 text-base" 
            placeholder="e.g. Plan me a trip to Fiji" 
            type="text"
            autoComplete="off"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          />
          <button 
            onClick={handleSend}
            disabled={!inputValue.trim()}
            className="flex-shrink-0 w-10 h-10 rounded-lg bg-white/10 hover:bg-white/20 flex items-center justify-center text-white transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <Send size={18} />
          </button>
        </div>
      </div>
      <p className="text-center text-xs text-gray-400 mt-4 drop-shadow-sm">Multi-agent Travel Planner can make mistakes. Check important info.</p>
    </div>
  );
};
