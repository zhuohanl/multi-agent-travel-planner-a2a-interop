import { describe, expect, it } from "vitest";

import { buildItineraryViewModel } from "./itinerary-view-model";

describe("buildItineraryViewModel", () => {
  it("keeps legacy frontend itinerary shape renderable", () => {
    const legacy = {
      tripId: "trip-1",
      tripSequence: 2,
      createdAt: "2026-02-23T10:00:00Z",
      days: [
        {
          day: 1,
          theme: "Arrival",
          slots: [{ time: "AM", place: "Airport transfer" }],
        },
      ],
      budget: {
        target: 1000,
        currency: "AUD",
        total: 900,
        lodging: 400,
        food: 200,
        activities: 200,
        transport: 100,
      },
      deltas: [],
      suggestions: [],
      budgetStatus: "under",
      validated: true,
      violations: [],
      nextHandoff: [],
    };

    const result = buildItineraryViewModel(legacy);
    expect(result).not.toBeNull();
    expect(result?.days).toHaveLength(1);
    expect(result?.currency).toBe("AUD");
    expect(result?.budgetStatus).toBe("under");
  });

  it("converts backend itinerary draft to renderable timeline model", () => {
    const backendDraft = {
      consultation_id: "cons-1",
      created_at: "2026-02-23T10:00:00Z",
      trip_summary: {
        destination: "Fiji",
        start_date: "2026-09-25",
        end_date: "2026-09-30",
        travelers: 3,
      },
      days: [
        {
          day_number: 1,
          date: "2026-09-25",
          title: "Arrival & Resort",
          activities: [
            {
              name: "Check-in",
              location: "Hilton Fiji Beach Resort",
              start_time: "16:00",
              end_time: "16:30",
            },
          ],
          meals: [{ meal_type: "dinner", restaurant_name: "Sundowner Bar", location: "Denarau" }],
          transport: [
            {
              mode: "flight",
              from_location: "Melbourne",
              to_location: "Nadi",
              carrier: "Fiji Airways",
              departure_time: "08:30",
              arrival_time: "14:00",
            },
          ],
          accommodation: {
            name: "Hilton Fiji Beach Resort & Spa",
            location: "Denarau Island",
          },
        },
      ],
      total_estimated_cost: 10592,
      currency: "AUD",
      validation: {
        is_valid: false,
        issues: [{ code: "budget_overrun", message: "Over budget" }],
      },
    };

    const result = buildItineraryViewModel(backendDraft);
    expect(result).not.toBeNull();
    expect(result?.destination).toBe("Fiji");
    expect(result?.travelers).toBe(3);
    expect(result?.days[0].blocks.length).toBeGreaterThan(0);
    expect(result?.days[0].blocks.some((block) => block.timeLabel === "08:30-14:00")).toBe(true);
    expect(result?.days[0].blocks.some((block) => block.timeLabel === "16:00-16:30")).toBe(true);
    expect(result?.currency).toBe("AUD");
    expect(result?.totalEstimatedCost).toBe(10592);
    expect(result?.validated).toBe(false);
    expect(result?.violations.length).toBe(1);
  });

  it("returns null for non-object values", () => {
    expect(buildItineraryViewModel(null)).toBeNull();
    expect(buildItineraryViewModel(undefined)).toBeNull();
  });

  it("sorts backend day blocks chronologically by exact start time", () => {
    const backendDraft = {
      destination: "Fiji",
      start_date: "2026-09-25",
      end_date: "2026-09-25",
      days: [
        {
          day_number: 1,
          date: "2026-09-25",
          title: "Day 1 in Fiji",
          activities: [
            { name: "Late walk", start_time: "16:30", end_time: "18:30" },
            { name: "Afternoon stop", start_time: "14:30", end_time: "16:00" },
          ],
          meals: [
            { meal_type: "lunch", name: "Lunch", start_time: "12:30", end_time: "13:30" },
            { meal_type: "dinner", name: "Dinner", start_time: "19:00", end_time: "20:30" },
          ],
          transport: [
            {
              mode: "flight",
              from_location: "Melbourne",
              to_location: "Fiji",
              departure_time: "09:00",
              arrival_time: "14:00",
            },
          ],
        },
      ],
    };

    const result = buildItineraryViewModel(backendDraft);
    expect(result).not.toBeNull();
    const labels = result?.days[0].blocks.map((block) => block.timeLabel);
    expect(labels).toEqual(["09:00-14:00", "12:30-13:30", "14:30-16:00", "16:30-18:30", "19:00-20:30"]);
  });
});
