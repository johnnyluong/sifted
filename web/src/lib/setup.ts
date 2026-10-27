import type { SetupAnswer, SetupQuestion } from "@/api";

export type Answers = Record<string, SetupAnswer>;

export function startingAnswers(questions: SetupQuestion[], saved: SetupAnswer[]): Answers {
  const byId = new Map(saved.map((a) => [a.question_id, a]));
  return Object.fromEntries(
    questions.map((q) => [q.id, byId.get(q.id) ?? { question_id: q.id, text: "", picked: [] }]),
  );
}

export function pick(question: SetupQuestion, answer: SetupAnswer, choice: string): SetupAnswer {
  if (question.kind === "one") return { ...answer, picked: [choice] };
  const picked = answer.picked.includes(choice)
    ? answer.picked.filter((c) => c !== choice)
    : [...answer.picked, choice];
  return { ...answer, picked };
}

export function filledAnswers(questions: SetupQuestion[], answers: Answers): SetupAnswer[] {
  return questions.flatMap((q) => {
    const a = answers[q.id];
    const text = a?.text.trim() ?? "";
    return a && (text || a.picked.length > 0) ? [{ ...a, text }] : [];
  });
}
