export const SAMPLE_QUESTIONS = [
  "Show my usage for the last 30 days.",
  "Compare this month vs last month.",
  "Usage by site last month.",
  "What were my peak days?",
] as const;

export const SAMPLE_CARDS: { kind: string; question: (typeof SAMPLE_QUESTIONS)[number] }[] = [
  { kind: "Trend", question: SAMPLE_QUESTIONS[0] },
  { kind: "Compare", question: SAMPLE_QUESTIONS[1] },
  { kind: "Breakdown", question: SAMPLE_QUESTIONS[2] },
  { kind: "Peaks", question: SAMPLE_QUESTIONS[3] },
];
