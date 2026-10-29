import type { SetupAnswer, SetupQuestion } from "@/api";
import { ANSWER_MAX } from "@/lib/limits";

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
    const text = (a && q.other ? writeIns(a).join("; ") : a?.text.trim()) ?? "";
    return a && (text || a.picked.length > 0) ? [{ ...a, text }] : [];
  });
}

const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();

function split(text: string): string[] {
  return text
    .split(";")
    .map((w) => w.trim())
    .filter(Boolean);
}

export function writeIns(answer: SetupAnswer): string[] {
  return split(answer.text).filter((w, i, all) => all.findIndex((o) => same(o, w)) === i);
}

export function addWriteIn(question: SetupQuestion, answer: SetupAnswer, typed: string): SetupAnswer | null {
  let next = answer;
  for (const label of split(typed)) {
    const choice = question.choices.find((c) => same(c.label, label));
    const current = writeIns(next);
    if (choice) next = next.picked.includes(choice.id) ? next : pick(question, next, choice.id);
    else if (!current.some((w) => same(w, label))) next = { ...next, text: [...current, label].join("; ") };
  }
  return next.text.length > ANSWER_MAX ? null : next;
}

export function removeWriteIn(answer: SetupAnswer, label: string): SetupAnswer {
  return {
    ...answer,
    text: writeIns(answer)
      .filter((w) => !same(w, label))
      .join("; "),
  };
}

export function withTyped(
  questions: SetupQuestion[],
  answers: Answers,
  typed: Record<string, string>,
): Record<string, SetupAnswer | null> {
  return Object.fromEntries(
    questions.flatMap((q) => {
      const a = answers[q.id];
      return a ? [[q.id, addWriteIn(q, a, typed[q.id] ?? "")]] : [];
    }),
  );
}
