export type ItineraryPeriod = "AM" | "PM" | "EVE" | "ANY";

export interface ItineraryBlock {
  period: ItineraryPeriod;
  timeLabel?: string;
  title: string;
  details?: string;
  mapUrl?: string | null;
  url?: string | null;
}

export interface ItineraryDayView {
  dayNumber: number;
  title: string;
  date?: string;
  blocks: ItineraryBlock[];
}

export interface ItineraryViewModel {
  destination: string;
  startDate?: string;
  endDate?: string;
  travelers: number | null;
  days: ItineraryDayView[];
  totalEstimatedCost: number;
  currency: string;
  budgetStatus: string;
  validated: boolean;
  violations: Array<Record<string, unknown>>;
  highlights: string[];
  gaps: Array<Record<string, unknown>>;
}

const PERIOD_RANK: Record<ItineraryPeriod, number> = { AM: 0, PM: 1, EVE: 2, ANY: 3 };

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function asNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return undefined;
}

function inferPeriodFromHour(hour: number): ItineraryPeriod {
  if (hour < 12) {
    return "AM";
  }
  if (hour < 18) {
    return "PM";
  }
  return "EVE";
}

function parseHourFromText(value: string): number | null {
  const hhmm = value.match(/(\d{1,2}):(\d{2})/);
  if (hhmm) {
    return Number.parseInt(hhmm[1], 10);
  }
  const iso = value.match(/T(\d{1,2}):(\d{2})/);
  if (iso) {
    return Number.parseInt(iso[1], 10);
  }
  return null;
}

function parseStartMinuteFromText(value: string | undefined): number | null {
  if (!value) {
    return null;
  }
  const match = value.match(/(\d{1,2}):(\d{2})/);
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

function compareBlocksChronologically(a: ItineraryBlock, b: ItineraryBlock): number {
  const startA = parseStartMinuteFromText(a.timeLabel);
  const startB = parseStartMinuteFromText(b.timeLabel);
  if (startA !== null && startB !== null) {
    return startA - startB;
  }
  if (startA !== null) {
    return -1;
  }
  if (startB !== null) {
    return 1;
  }
  return PERIOD_RANK[a.period] - PERIOD_RANK[b.period];
}

function parsePeriod(value: unknown, fallback: ItineraryPeriod = "ANY"): ItineraryPeriod {
  const text = asString(value);
  if (!text) {
    return fallback;
  }

  const upper = text.toUpperCase();
  if (upper === "AM" || upper === "PM" || upper === "EVE") {
    return upper;
  }

  const hour = parseHourFromText(text);
  if (hour !== null) {
    return inferPeriodFromHour(hour);
  }

  if (upper.includes("BREAKFAST")) {
    return "AM";
  }
  if (upper.includes("LUNCH")) {
    return "PM";
  }
  if (upper.includes("DINNER")) {
    return "EVE";
  }
  return fallback;
}

function extractStartTime(item: Record<string, unknown>): string | undefined {
  const direct =
    asString(item.start_time) ??
    asString(item.departure_time) ??
    asString(item.time) ??
    asString(item.startTime);
  if (direct) {
    return direct;
  }

  const timeSlot = item.time_slot ?? item.timeSlot;
  const slotRecord = asRecord(timeSlot);
  if (slotRecord) {
    return (
      asString(slotRecord.start_time) ??
      asString(slotRecord.startTime) ??
      asString(slotRecord.label)
    );
  }

  return asString(timeSlot);
}

function extractEndTime(item: Record<string, unknown>): string | undefined {
  const direct =
    asString(item.end_time) ??
    asString(item.arrival_time) ??
    asString(item.endTime);
  if (direct) {
    return direct;
  }

  const timeSlot = item.time_slot ?? item.timeSlot;
  const slotRecord = asRecord(timeSlot);
  if (slotRecord) {
    return asString(slotRecord.end_time) ?? asString(slotRecord.endTime);
  }

  return undefined;
}

function formatClock(value: string | undefined): string | undefined {
  if (!value) {
    return undefined;
  }
  const match = value.match(/(?:T)?(\d{1,2}):(\d{2})/);
  if (!match) {
    return undefined;
  }
  return `${match[1].padStart(2, "0")}:${match[2]}`;
}

function buildTimeLabel(
  startRaw: string | undefined,
  endRaw: string | undefined,
  fallbackPeriod: ItineraryPeriod
): string {
  const start = formatClock(startRaw);
  const end = formatClock(endRaw);
  if (start && end) {
    return `${start}-${end}`;
  }
  if (start) {
    return start;
  }
  if (end) {
    return `Until ${end}`;
  }
  return fallbackPeriod;
}

function joinDetails(parts: Array<string | undefined>): string | undefined {
  const filtered = parts.filter((part): part is string => Boolean(part));
  return filtered.length ? filtered.join(" | ") : undefined;
}

function normalizeLegacyDay(day: Record<string, unknown>, index: number): ItineraryDayView {
  const slots = asArray(day.slots)
    .map((slotRaw) => {
      const slot = asRecord(slotRaw);
      if (!slot) {
        return null;
      }
      const title = asString(slot.place);
      if (!title) {
        return null;
      }
      const period = parsePeriod(slot.time, "ANY");
      const rawTime = asString(slot.time);
      return {
        period,
        timeLabel: rawTime ?? period,
        title,
        details: joinDetails([asString(slot.walkMins) ? `${slot.walkMins} min walk` : undefined, asString(slot.train)]),
        mapUrl: asString(slot.mapUrl) ?? null,
        url: asString(slot.url) ?? null,
      } satisfies ItineraryBlock;
    })
    .filter((item): item is ItineraryBlock => item !== null);

  return {
    dayNumber: asNumber(day.day) ?? index + 1,
    title: asString(day.theme) ?? "Curated experiences",
    blocks: slots.length ? slots : [{ period: "ANY", title: "Free time / buffer" }],
  };
}

function normalizeBackendDay(day: Record<string, unknown>, index: number): ItineraryDayView {
  const blocks: ItineraryBlock[] = [];

  for (const transportRaw of asArray(day.transport)) {
    const transport = asRecord(transportRaw);
    if (!transport) {
      continue;
    }
    const mode = asString(transport.mode) ?? "Transport";
    const from = asString(transport.from_location);
    const to = asString(transport.to_location);
    const title = from && to ? `${mode}: ${from} to ${to}` : mode;
    const startTime = extractStartTime(transport);
    const endTime = extractEndTime(transport);
    const period = parsePeriod(startTime, "AM");
    blocks.push({
      period,
      timeLabel: buildTimeLabel(startTime, endTime, period),
      title,
      details: joinDetails([asString(transport.carrier), asString(transport.notes)]),
      mapUrl: asString(transport.map_url) ?? asString(transport.mapUrl) ?? null,
      url: asString(transport.url) ?? null,
    });
  }

  for (const activityRaw of asArray(day.activities)) {
    const activity = asRecord(activityRaw);
    if (!activity) {
      continue;
    }
    const title = asString(activity.name) ?? asString(activity.title);
    if (!title) {
      continue;
    }
    const startTime = extractStartTime(activity);
    const endTime = extractEndTime(activity);
    const period = parsePeriod(startTime, "PM");
    blocks.push({
      period,
      timeLabel: buildTimeLabel(startTime, endTime, period),
      title,
      details: joinDetails([asString(activity.location), asString(activity.description), asString(activity.notes)]),
      mapUrl: asString(activity.map_url) ?? asString(activity.mapUrl) ?? null,
      url: asString(activity.url) ?? null,
    });
  }

  for (const mealRaw of asArray(day.meals)) {
    const meal = asRecord(mealRaw);
    if (!meal) {
      continue;
    }
    const mealType = asString(meal.meal_type) ?? "Meal";
    const mealName = asString(meal.restaurant_name) ?? asString(meal.name);
    const title = mealName ? `${mealType}: ${mealName}` : mealType;
    const startTime = extractStartTime(meal);
    const endTime = extractEndTime(meal);
    const period = parsePeriod(startTime ?? mealType, "PM");
    blocks.push({
      period,
      timeLabel: buildTimeLabel(startTime, endTime, period),
      title,
      details: joinDetails([asString(meal.location), asString(meal.cuisine), asString(meal.notes)]),
      mapUrl: asString(meal.map_url) ?? asString(meal.mapUrl) ?? null,
      url: asString(meal.url) ?? null,
    });
  }

  const accommodation = asRecord(day.accommodation);
  if (accommodation) {
    const stayName = asString(accommodation.name) ?? "Accommodation";
    const startTime = extractStartTime(accommodation);
    const endTime = extractEndTime(accommodation);
    const period = parsePeriod(startTime, "EVE");
    blocks.push({
      period,
      timeLabel: buildTimeLabel(startTime, endTime, period),
      title: `Stay: ${stayName}`,
      details: joinDetails([asString(accommodation.location), asString(accommodation.room_type)]),
      mapUrl: asString(accommodation.map_url) ?? asString(accommodation.mapUrl) ?? null,
      url: asString(accommodation.url) ?? null,
    });
  }

  blocks.sort(compareBlocksChronologically);

  return {
    dayNumber: asNumber(day.day_number) ?? asNumber(day.day) ?? index + 1,
    title: asString(day.title) ?? asString(day.theme) ?? "Curated experiences",
    date: asString(day.date),
    blocks: blocks.length ? blocks : [{ period: "ANY", title: "Free time / buffer" }],
  };
}

function toViolationList(validation: Record<string, unknown> | null): Array<Record<string, unknown>> {
  if (!validation) {
    return [];
  }
  const issues = asArray(validation.issues).filter((issue): issue is Record<string, unknown> => asRecord(issue) !== null);
  const errors = asArray(validation.errors).filter((issue): issue is Record<string, unknown> => asRecord(issue) !== null);
  const warnings = asArray(validation.warnings).map((item) =>
    typeof item === "string" ? ({ message: item } as Record<string, unknown>) : (asRecord(item) ?? { warning: "warning" })
  );
  return [...issues, ...errors, ...warnings];
}

function listHighlights(days: ItineraryDayView[]): string[] {
  const highlights: string[] = [];
  for (const day of days) {
    for (const block of day.blocks) {
      if (block.title.startsWith("Stay:")) {
        continue;
      }
      highlights.push(block.title);
      if (highlights.length >= 6) {
        return highlights;
      }
    }
  }
  return highlights;
}

export function buildItineraryViewModel(raw: unknown): ItineraryViewModel | null {
  const record = asRecord(raw);
  if (!record) {
    return null;
  }

  const rawDays = asArray(record.days).map((item) => asRecord(item)).filter((item): item is Record<string, unknown> => item !== null);
  if (rawDays.length === 0) {
    return null;
  }

  const budget = asRecord(record.budget);
  const tripSummary = asRecord(record.trip_summary) ?? asRecord(record.tripSummary);
  const validation = asRecord(record.validation);

  const isLegacy = budget !== null;
  const days = rawDays.map((day, index) => (isLegacy ? normalizeLegacyDay(day, index) : normalizeBackendDay(day, index)));

  const destination =
    asString(record.destination) ??
    asString(tripSummary?.destination) ??
    "Travel Itinerary";

  const totalEstimatedCost =
    asNumber(record.total_estimated_cost) ??
    asNumber(record.totalEstimatedCost) ??
    asNumber(budget?.total) ??
    0;

  const currency =
    asString(record.currency) ??
    asString(budget?.currency) ??
    "USD";

  const budgetStatus =
    asString(record.budget_status) ??
    asString(record.budgetStatus) ??
    (totalEstimatedCost > 0 ? "estimated" : "pending");

  const violations = toViolationList(validation);
  const validated =
    typeof validation?.is_valid === "boolean"
      ? Boolean(validation.is_valid)
      : violations.length === 0;

  const gaps = asArray(record.gaps)
    .map((gap) => asRecord(gap))
    .filter((gap): gap is Record<string, unknown> => gap !== null);

  const explicitHighlights = asArray(record.highlights).filter((item): item is string => typeof item === "string" && item.trim().length > 0);
  const highlights = explicitHighlights.length ? explicitHighlights : listHighlights(days);

  return {
    destination,
    startDate: asString(tripSummary?.start_date) ?? asString(record.start_date),
    endDate: asString(tripSummary?.end_date) ?? asString(record.end_date),
    travelers: asNumber(tripSummary?.travelers) ?? asNumber(record.num_travelers) ?? null,
    days,
    totalEstimatedCost,
    currency,
    budgetStatus,
    validated,
    violations,
    highlights,
    gaps,
  };
}
