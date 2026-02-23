import React, { useEffect, useMemo, useRef } from "react";
import { ExternalLink, MapPin, Maximize2 } from "lucide-react";

import { buildItineraryViewModel, type ItineraryPeriod } from "../itinerary-view-model";

const FALLBACK_IMAGE = "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1600&q=80";

interface ItineraryProps {
  itinerary: Record<string, unknown> | null;
  standalone?: boolean;
}

function renderDateRange(startDate?: string, endDate?: string): string {
  if (startDate && endDate) {
    return `${startDate} - ${endDate}`;
  }
  if (startDate) {
    return startDate;
  }
  if (endDate) {
    return endDate;
  }
  return "Dates to be confirmed";
}

function toHumanDate(value?: string): string | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

function periodOrder(period: ItineraryPeriod): number {
  if (period === "AM") {
    return 0;
  }
  if (period === "PM") {
    return 1;
  }
  if (period === "EVE") {
    return 2;
  }
  return 3;
}

function parseStartMinute(label: string | undefined): number | null {
  if (!label) {
    return null;
  }
  const match = label.match(/(\d{1,2}):(\d{2})/);
  if (!match) {
    return null;
  }
  const hour = Number.parseInt(match[1], 10);
  const minute = Number.parseInt(match[2], 10);
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) {
    return null;
  }
  return hour * 60 + minute;
}

function compareBlocksChronologically(
  a: { period: ItineraryPeriod; timeLabel?: string },
  b: { period: ItineraryPeriod; timeLabel?: string }
): number {
  const startA = parseStartMinute(a.timeLabel);
  const startB = parseStartMinute(b.timeLabel);
  if (startA !== null && startB !== null) {
    return startA - startB;
  }
  if (startA !== null) {
    return -1;
  }
  if (startB !== null) {
    return 1;
  }
  return periodOrder(a.period) - periodOrder(b.period);
}

function renderDayHeading(dayNumber: number, title: string): string {
  const regex = new RegExp(`^day\\s*${dayNumber}\\s*[:\\-]?\\s*`, "i");
  const cleaned = title.replace(regex, "").trim();
  if (!cleaned) {
    return `Day ${dayNumber}`;
  }
  return `Day ${dayNumber}: ${cleaned}`;
}

export const Itinerary: React.FC<ItineraryProps> = ({ itinerary, standalone = false }) => {
  const model = useMemo(() => buildItineraryViewModel(itinerary), [itinerary]);
  const scrollAreaRef = useRef<HTMLDivElement | null>(null);
  const scrollTopRef = useRef(0);

  useEffect(() => {
    const node = scrollAreaRef.current;
    if (!node) {
      return;
    }
    node.scrollTop = scrollTopRef.current;
  }, [model]);

  if (!model) {
    if (standalone) {
      return (
        <div className="min-h-screen bg-gray-100 p-4 md:p-8">
          <div className="max-w-4xl mx-auto bg-white rounded-2xl shadow-xl p-8 text-center text-gray-700">
            Itinerary will appear here once the agents finish planning.
          </div>
        </div>
      );
    }
    return null;
  }

  const renderItineraryContent = (expanded = false) => (
    <div
      className={`bg-white w-full ${
        expanded ? "h-full flex flex-col" : "border border-gray-200 rounded-xl shadow-sm overflow-hidden flex flex-col"
      }`}
    >
      <div
        className={`${expanded ? "h-80" : "h-48"} bg-cover bg-center relative transition-all duration-300 flex-shrink-0`}
        style={{ backgroundImage: `url(${FALLBACK_IMAGE})` }}
      >
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent flex items-end p-6">
          <div className="text-white">
            <h2 className={`${expanded ? "text-5xl" : "text-3xl"} font-bold transition-all`}>
              {model.destination} Trip - {model.days.length} day{model.days.length === 1 ? "" : "s"}
            </h2>
            <p className={`${expanded ? "text-lg" : "text-sm"} opacity-90 mt-2`}>
              {model.travelers ? `Travelers: ${model.travelers} | ` : ""}
              {renderDateRange(model.startDate, model.endDate)}
            </p>
          </div>
        </div>
      </div>

      <div
        ref={scrollAreaRef}
        onScroll={(event) => {
          scrollTopRef.current = event.currentTarget.scrollTop;
        }}
        className={`p-6 overflow-y-auto ${expanded ? "flex-1" : "max-h-[500px]"}`}
      >
        <div className="mb-6 grid gap-4 sm:grid-cols-3">
          <div className="p-4 bg-sky-50 rounded-lg border border-sky-100">
            <h4 className="font-bold text-sky-800 mb-2 text-sm uppercase tracking-wide">Budget</h4>
            <p className="text-gray-800 text-lg font-semibold">
              {model.currency} {Math.round(model.totalEstimatedCost)}
            </p>
            <p className="text-xs text-gray-600 mt-1">Status: {model.budgetStatus}</p>
          </div>
          <div className="p-4 bg-emerald-50 rounded-lg border border-emerald-100">
            <h4 className="font-bold text-emerald-800 mb-2 text-sm uppercase tracking-wide">Validation</h4>
            <p className={`text-sm font-semibold ${model.validated ? "text-emerald-700" : "text-rose-700"}`}>
              {model.validated ? "Validator passed" : "Validator flagged items"}
            </p>
            <p className="text-xs text-gray-600 mt-1">Violations: {model.violations.length}</p>
          </div>
          <div className="p-4 bg-amber-50 rounded-lg border border-amber-100">
            <h4 className="font-bold text-amber-800 mb-2 text-sm uppercase tracking-wide">Highlights</h4>
            <ul className="list-disc list-inside text-sm text-gray-700 space-y-1">
              {(model.highlights.length ? model.highlights : ["Route curated by the agent team"]).map((item, index) => (
                <li key={`${item}-${index}`}>{item}</li>
              ))}
            </ul>
          </div>
        </div>

        {model.days.map((day, index) => {
          const sortedBlocks = [...day.blocks].sort(compareBlocksChronologically);
          return (
            <div key={index} className="relative pl-8 pb-8 border-l-2 border-gray-200 last:border-0 last:pb-0 mt-2">
              <div className="absolute -left-[9px] top-0 w-4 h-4 rounded-full bg-sky-500 ring-4 ring-white"></div>
              <div className="flex flex-col sm:flex-row sm:justify-between sm:items-start mb-2">
                <h3 className="text-lg font-bold text-gray-900">
                  {renderDayHeading(day.dayNumber, day.title)}
                </h3>
                {toHumanDate(day.date) && (
                  <span className="text-xs font-medium text-gray-500 bg-gray-100 px-2 py-1 rounded">
                    {toHumanDate(day.date)}
                  </span>
                )}
              </div>
              <div className="space-y-4 text-sm text-gray-600">
                {sortedBlocks.map((block, blockIndex) => (
                  <div key={blockIndex} className="flex gap-3 items-start">
                    <span className="font-bold text-gray-800 min-w-[95px] pt-0.5">{block.timeLabel ?? block.period}</span>
                    <div className="flex flex-col gap-1.5">
                      <span className="text-gray-800">{block.title}</span>
                      {block.details && <span className="text-xs text-gray-500">{block.details}</span>}
                      <div className="flex items-center gap-4">
                        {block.mapUrl && (
                          <a
                            href={block.mapUrl}
                            className="flex items-center gap-1 text-xs font-medium text-sky-600 hover:text-sky-800 hover:underline transition-colors"
                            target="_blank"
                            rel="noreferrer"
                          >
                            <MapPin size={12} />
                            Map
                          </a>
                        )}
                        {block.url && (
                          <a
                            href={block.url}
                            className="flex items-center gap-1 text-xs font-medium text-sky-600 hover:text-sky-800 hover:underline transition-colors"
                            target="_blank"
                            rel="noreferrer"
                          >
                            <ExternalLink size={12} />
                            Details
                          </a>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <div className="bg-gray-50 p-3 border-t border-gray-200 flex justify-between items-center mt-auto flex-shrink-0">
        <div className="text-xs text-gray-600">
          Budget {model.currency} {Math.round(model.totalEstimatedCost)} · Status {model.budgetStatus}
        </div>
        <div className="flex items-center gap-3">
          <button className="text-sky-600 text-sm font-semibold hover:underline">Download PDF</button>
          <button className="text-sky-600 text-sm font-semibold hover:underline">Modify Itinerary</button>
        </div>
      </div>
    </div>
  );

  if (standalone) {
    return (
      <div className="min-h-screen bg-gray-100 p-4 md:p-8">
        <div className="max-w-5xl mx-auto bg-white rounded-2xl shadow-xl overflow-hidden min-h-[calc(100vh-4rem)] flex flex-col">
          {renderItineraryContent(true)}
        </div>
      </div>
    );
  }

  return (
    <div className="relative group my-4 max-w-3xl">
      <button
        onClick={() => window.open("?mode=itinerary", "_blank")}
        className="absolute top-4 right-4 z-10 p-2 bg-black/20 hover:bg-black/40 text-white rounded-full backdrop-blur-sm transition-all opacity-0 group-hover:opacity-100"
        title="Open Full Itinerary in New Tab"
      >
        <Maximize2 size={18} />
      </button>
      {renderItineraryContent()}
    </div>
  );
};
